"""Execute policy-approved live intents, one bounded broker session per intent.

The session follows docs/execution/EXECUTOR.md: it builds the packet through the
trusted CLI, reviews and places the exact packet through Robinhood, and records
the lifecycle through the same CLI. Afterwards this module checks the ledger
against the session's own report so a placed-but-unrecorded order is loud.
"""

import argparse
import json
import os
import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.broker.collector import default_codex_home
from app.broker.config import get_live_profile, load_live_profiles
from app.broker.session import BrokerSessionFailure, run_broker_session
from app.schemas.live_execution import ExecutionProfile
from app.schemas.order_intent import OrderIntent
from app.storage.database import connect
from app.x.calendar import completed_session, session_close

DEFAULT_EXECUTION_MODEL = "gpt-5.6-sol"
PLACED_OUTCOMES = {"submitted", "partially_filled", "filled"}
# An entry band is anchored to the price the model actually checked, so an intent is
# executable only in its own session or the next one. Anything older needs a new review.
# Attempts are capped because a packet that keeps failing its band would otherwise burn
# one execution session on every tick of the market-hours schedule.
MAX_ATTEMPTS_PER_INTENT = 3
MIN_RETRY_INTERVAL = timedelta(minutes=15)


class ExecutionReport(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    order_intent_id: str = Field(min_length=1)
    outcome: Literal[
        "filled",
        "partially_filled",
        "submitted",
        "canceled",
        "review_rejected",
        "not_placed",
        "failed",
        "blocked",
    ]
    execution_packet_id: str | None = None
    broker_execution_record_id: str | None = None
    broker_order_id: str | None = None
    notes: str = Field(default="", max_length=2000)


def session_boundary(now: datetime) -> datetime | None:
    """Close of the last completed session: intents older than this are stale."""
    return session_close(completed_session(now))


def pending_live_intents(
    conn: sqlite3.Connection, profile: ExecutionProfile, *, now: datetime
) -> list[OrderIntent]:
    rows = conn.execute(
        """
        SELECT intent_json FROM order_intents
        WHERE execution_mode = 'LIVE' AND execution_profile_id = ?
          AND order_intent_id NOT IN (SELECT order_intent_id FROM broker_execution_records)
        ORDER BY created_at
        """,
        (profile.execution_profile_id,),
    ).fetchall()
    intents = [OrderIntent.model_validate_json(row[0]) for row in rows]
    boundary = session_boundary(now)
    return [intent for intent in intents if boundary is None or intent.created_at >= boundary]


def attempt_history(ledger: Path, since: datetime | None) -> dict[str, tuple[int, datetime]]:
    if not ledger.is_file():
        return {}
    seen: dict[str, list[datetime]] = {}
    for line in ledger.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            attempted_at = datetime.fromisoformat(row["attempted_at"])
        except (ValueError, KeyError, TypeError):
            continue
        if since is None or attempted_at >= since:
            seen.setdefault(str(row.get("order_intent_id", "")), []).append(attempted_at)
    return {key: (len(values), max(values)) for key, values in seen.items()}


def execution_prompt(intent: OrderIntent, profile: ExecutionProfile) -> str:
    return (
        "You are the execution-only worker for an autonomous investment harness, launched "
        "unattended. Read docs/execution/EXECUTOR.md first and follow it exactly, including its "
        "tool and record mapping section. Execute exactly one order intent: "
        f"{intent.order_intent_id} ({intent.side.value} {intent.ticker}, target weight "
        f"{intent.target_weight}) for execution profile {profile.execution_profile_id}, "
        f"account alias {profile.account_alias}, account fingerprint "
        f"{profile.broker_account_fingerprint}. Limits: maximum order notional "
        f"${profile.max_order_notional:.2f}, maximum quote age "
        f"{profile.max_quote_age_seconds} seconds, maximum spread "
        f"{profile.max_spread_bps} bps. Run repository commands with the python on PATH from "
        "the repository root and write files only under data/broker/. Never run git. Never "
        "research, resize, substitute a ticker or account, or continue to another intent. Place "
        "at most one order, using the execution packet ID as ref_id. If placement returns an "
        "ambiguous error, query get_equity_orders before any retry and never place again while "
        "an order with that ref_id may exist. Do not ask questions; no human will answer. Finish "
        "by returning only the JSON object required by the schema, with notes summarizing what "
        "the broker reported."
    )


def verify_report(
    conn: sqlite3.Connection, intent: OrderIntent, report: ExecutionReport
) -> list[str]:
    problems = []
    row = conn.execute(
        "SELECT broker_execution_record_id, broker_order_id, execution_packet_id "
        "FROM broker_execution_records WHERE order_intent_id = ?",
        (intent.order_intent_id,),
    ).fetchone()
    if report.order_intent_id != intent.order_intent_id:
        problems.append("report_intent_mismatch")
    if report.outcome in PLACED_OUTCOMES:
        if row is None:
            problems.append("unrecorded_submission")
        elif report.broker_order_id and row[1] != report.broker_order_id:
            problems.append("broker_order_id_mismatch")
    elif row is not None:
        problems.append("record_without_reported_placement")
    if report.execution_packet_id:
        packet = conn.execute(
            "SELECT 1 FROM live_execution_packets WHERE execution_packet_id = ?",
            (report.execution_packet_id,),
        ).fetchone()
        if packet is None:
            problems.append("reported_packet_missing")
    return problems


def execute_pending(
    db_path: str | Path,
    profile: ExecutionProfile,
    *,
    model: str = DEFAULT_EXECUTION_MODEL,
    codex_home: str | Path | None = None,
    repo_root: str | Path = ".",
    log_dir: Path,
    now: datetime | None = None,
    session: Callable[..., Any] = run_broker_session,
    max_intents: int = 3,
) -> list[dict[str, Any]]:
    if not profile.enabled:
        raise ValueError(f"execution profile {profile.execution_profile_id} is disabled")
    started = now or datetime.now(UTC)
    with closing(connect(db_path)) as conn:
        intents = pending_live_intents(conn, profile, now=started)[:max_intents]
    results: list[dict[str, Any]] = []
    log_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = log_dir / "executions.jsonl"
    history = attempt_history(ledger_path, session_boundary(started))
    for intent in intents:
        attempts, last_attempt = history.get(intent.order_intent_id, (0, None))
        if attempts >= MAX_ATTEMPTS_PER_INTENT:
            results.append(
                {"order_intent_id": intent.order_intent_id, "skipped": "attempt_cap_reached"}
            )
            continue
        if last_attempt is not None and started - last_attempt < MIN_RETRY_INTERVAL:
            results.append({"order_intent_id": intent.order_intent_id, "skipped": "retry_backoff"})
            continue
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        result: dict[str, Any] = {
            "order_intent_id": intent.order_intent_id,
            "ticker": intent.ticker,
            "side": intent.side.value,
            "attempted_at": started.isoformat(),
        }
        try:
            report = session(
                execution_prompt(intent, profile),
                schema=ExecutionReport,
                model=model,
                codex_home=codex_home or default_codex_home(),
                sandbox="workspace-write",
                cwd=repo_root,
                timeout_seconds=900,
                log_path=log_dir / f"execute-{intent.order_intent_id}-{stamp}.log",
            )
        except BrokerSessionFailure as error:
            report = None
            result["session_failure"] = str(error)
        with closing(connect(db_path)) as conn:
            if report is not None:
                result["report"] = report.model_dump(mode="json")
                result["problems"] = verify_report(conn, intent, report)
            else:
                row = conn.execute(
                    "SELECT broker_order_id FROM broker_execution_records WHERE order_intent_id=?",
                    (intent.order_intent_id,),
                ).fetchone()
                result["problems"] = [
                    "session_failed_after_submission" if row else "session_failed"
                ]
        with ledger_path.open("a", encoding="utf-8") as ledger:
            ledger.write(json.dumps(result) + "\n")
        results.append(result)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.broker.executor")
    parser.add_argument("--db", default="data/boustrategy.db")
    parser.add_argument("--profiles", default="ops/live.local.json")
    parser.add_argument("--profile", default="codex")
    parser.add_argument("--model", default=DEFAULT_EXECUTION_MODEL)
    parser.add_argument("--codex-home", default=default_codex_home())
    parser.add_argument("--logs", default="data/logs/broker")
    parser.add_argument("--max-intents", type=int, default=3)
    args = parser.parse_args()
    profile = get_live_profile(load_live_profiles(args.profiles), args.profile)
    results = execute_pending(
        args.db,
        profile,
        model=args.model,
        codex_home=args.codex_home,
        repo_root=os.getcwd(),
        log_dir=Path(args.logs),
        max_intents=args.max_intents,
    )
    print(json.dumps({"executed": results}))
    if any(item.get("problems") for item in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
