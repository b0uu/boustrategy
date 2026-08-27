import argparse
import hashlib
import json
import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.broker.config import get_live_profile, load_live_profiles
from app.events.fetch import FOMC_COVERAGE_END
from app.events.store import parse_watchlist, refresh_earnings, sync_fomc
from app.paper.broker import settle
from app.paper.context import portfolio_context, position_tickers
from app.prices.cache import refresh_ticker
from app.reason.live_context import live_portfolio_context
from app.regime.run import latest_published_regime, score_date
from app.schemas.decision_record import RegimeState
from app.schemas.live_execution import ExecutionProfile
from app.schemas.order_intent import ExecutionMode
from app.schemas.reasoning_run import ReasoningRun, ReasoningRunResult, reasoning_run_id
from app.state.pipeline import DecisionStatus, ProcessOutcome, process_decision
from app.storage.database import connect
from app.storage.records import (
    complete_reasoning_run,
    get_live_portfolio_snapshot,
    get_reasoning_run,
    save_reasoning_run,
)
from app.triggers.evaluate import evaluate_triggers
from app.triggers.store import mark_triggers

from .intake import build_intake

_CONSIDERED_STATUSES = {
    DecisionStatus.POLICY_APPROVED,
    DecisionStatus.POLICY_REJECTED,
    DecisionStatus.ORDER_INTENT_CREATED,
}
LIVE_SNAPSHOT_MAX_AGE = timedelta(minutes=5)


class PreparationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_date: date
    prepared_at: datetime
    digest_path: str
    completed_digest_runs: list[str]
    refreshed_price_bars: dict[str, int]
    refreshed_calendar_events: dict[str, int]
    fills_created: int
    intents_awaiting_price: int
    trigger_counts: dict[str, int]
    regime: RegimeState
    raw_regime: RegimeState
    regime_score: int
    bundle_path: str


def _completed_digest_runs(conn: sqlite3.Connection, on_date: date, digest_path: Path) -> list[str]:
    if not digest_path.is_file():
        raise FileNotFoundError(f"missing same-day digest: {digest_path}")
    rows = conn.execute(
        """
        SELECT run_id, status FROM x_runs
        WHERE substr(run_id, 1, 10) = ? ORDER BY started_at, run_id
        """,
        (on_date.isoformat(),),
    ).fetchall()
    if not rows:
        raise ValueError(f"no digester run recorded for {on_date}")
    incomplete = [f"{run_id}:{status}" for run_id, status in rows if status != "digested"]
    if incomplete:
        raise ValueError(f"digester runs aren't complete: {', '.join(incomplete)}")
    return [run_id for run_id, _ in rows]


def _pending_intent_dates(conn: sqlite3.Connection) -> dict[str, date]:
    rows = conn.execute(
        """
        SELECT o.ticker, MIN(substr(o.created_at, 1, 10))
        FROM order_intents o
        LEFT JOIN paper_fills f ON f.order_intent_id = o.order_intent_id
        WHERE f.fill_id IS NULL
        GROUP BY o.ticker ORDER BY o.ticker
        """
    ).fetchall()
    return {ticker: date.fromisoformat(created_at) for ticker, created_at in rows}


def prepare_session(
    conn: sqlite3.Connection,
    on_date: date,
    out_dir: str | Path,
    *,
    digest_dir: str | Path = "data/digests",
    watchlist_path: str | Path = "docs/watchlist.md",
) -> PreparationResult:
    digest_path = Path(digest_dir) / f"{on_date.isoformat()}.md"
    completed_runs = _completed_digest_runs(conn, on_date, digest_path)

    pending = _pending_intent_dates(conn)
    tracked_tickers = sorted(
        set(parse_watchlist(watchlist_path)) | set(position_tickers(conn)) | set(pending)
    )
    default_start = on_date - timedelta(days=35)
    refresh_starts = {
        ticker: min(default_start, pending.get(ticker, on_date) - timedelta(days=7))
        for ticker in tracked_tickers
    }
    regime_start = on_date - timedelta(days=760)
    for ticker in ("SPY", "QQQ"):
        refresh_starts[ticker] = min(refresh_starts.get(ticker, on_date), regime_start)

    refreshed: dict[str, int] = {}
    for ticker, start in sorted(refresh_starts.items()):
        refreshed[ticker] = refresh_ticker(conn, ticker, start, on_date + timedelta(days=1))

    fills, awaiting = settle(conn, through_date=on_date)
    calendar_counts = {
        ticker: refresh_earnings(conn, ticker, today=on_date) for ticker in tracked_tickers
    }
    calendar_counts["FOMC"] = sync_fomc(conn, FOMC_COVERAGE_END)
    trigger_counts = evaluate_triggers(conn, tracked_tickers, on_date)
    published, score = score_date(conn, on_date)
    bundle_path = build_intake(conn, on_date, out_dir, digest_dir)
    result = PreparationResult(
        session_date=on_date,
        prepared_at=datetime.now(UTC),
        digest_path=digest_path.as_posix(),
        completed_digest_runs=completed_runs,
        refreshed_price_bars=refreshed,
        refreshed_calendar_events=calendar_counts,
        fills_created=fills,
        intents_awaiting_price=awaiting,
        trigger_counts=trigger_counts,
        regime=published,
        raw_regime=score.raw_regime,
        regime_score=score.score,
        bundle_path=bundle_path.as_posix(),
    )
    receipt_path = Path(out_dir) / "preparation.json"
    receipt_path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return result


def prepare_live_runs(
    conn: sqlite3.Connection,
    on_date: date,
    slot: str,
    out_dir: str | Path,
    profiles: list[tuple[str, str, str]],
    *,
    digest_dir: str | Path = "data/digests",
    started_at: datetime | None = None,
) -> list[ReasoningRun]:
    bundle_path = build_intake(conn, on_date, out_dir, digest_dir, live=True)
    bundle_hash = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    start = started_at or datetime.now(UTC)
    runs = []
    for execution_profile_id, model_label, portfolio_snapshot_id in profiles:
        snapshot = get_live_portfolio_snapshot(conn, portfolio_snapshot_id)
        if snapshot is None:
            raise ValueError(f"missing portfolio snapshot {portfolio_snapshot_id}")
        if snapshot.execution_profile_id != execution_profile_id:
            raise ValueError("portfolio snapshot profile mismatch")
        run = ReasoningRun(
            reasoning_run_id=reasoning_run_id(on_date, slot, execution_profile_id),
            session_date=on_date,
            slot=slot,
            execution_profile_id=execution_profile_id,
            model_label=model_label,
            shared_bundle_path=bundle_path.as_posix(),
            shared_bundle_sha256=bundle_hash,
            portfolio_snapshot_id=portfolio_snapshot_id,
            started_at=start,
        )
        save_reasoning_run(conn, run)
        runs.append(run)
    return runs


def submit_decision(
    conn: sqlite3.Connection,
    record_data: dict[str, Any],
    on_date: date,
    consume_trigger_ids: list[str] | None = None,
    *,
    execution_mode: ExecutionMode = ExecutionMode.PAPER,
    execution_profile_id: str = "",
    reasoning_run_id: str = "",
    execution_profile: ExecutionProfile | None = None,
    submitted_at: datetime | None = None,
) -> ProcessOutcome:
    raw_ticker = record_data.get("ticker")
    ticker = raw_ticker if isinstance(raw_ticker, str) else None
    if execution_mode == ExecutionMode.PAPER:
        portfolio = portfolio_context(conn, on_date, exclude_ticker=ticker)
    else:
        if execution_profile is None or not execution_profile.enabled:
            raise ValueError("live submission requires an enabled execution profile")
        if execution_profile.execution_profile_id != execution_profile_id:
            raise ValueError("live submission profile mismatch")
        run = get_reasoning_run(conn, reasoning_run_id)
        if run is None:
            raise ValueError(f"missing reasoning run {reasoning_run_id}")
        if run.result != ReasoningRunResult.PREPARED:
            raise ValueError("reasoning run is not PREPARED")
        if run.execution_profile_id != execution_profile_id:
            raise ValueError("reasoning run profile mismatch")
        snapshot = get_live_portfolio_snapshot(conn, run.portfolio_snapshot_id)
        if snapshot is None:
            raise ValueError(f"missing portfolio snapshot {run.portfolio_snapshot_id}")
        if snapshot.execution_profile_id != execution_profile_id:
            raise ValueError("portfolio snapshot profile mismatch")
        if snapshot.broker_account_fingerprint != execution_profile.broker_account_fingerprint:
            raise ValueError("portfolio snapshot account mismatch")
        now = submitted_at or datetime.now(UTC)
        if snapshot.captured_at > now or now - snapshot.captured_at > LIVE_SNAPSHOT_MAX_AGE:
            raise ValueError("portfolio snapshot is stale")
        raw_decision_id = record_data.get("decision_id")
        if not isinstance(raw_decision_id, str) or not raw_decision_id.startswith(
            f"{reasoning_run_id}_"
        ):
            raise ValueError("live decision_id must use the reasoning run namespace")
        portfolio = live_portfolio_context(conn, snapshot, on_date, exclude_ticker=ticker)
    true_regime_state = latest_published_regime(conn, on_date)
    if execution_mode == ExecutionMode.LIVE:
        conn.execute("BEGIN")
        try:
            outcome = process_decision(
                conn,
                record_data,
                portfolio,
                true_regime_state,
                received_at=submitted_at,
                execution_mode=execution_mode,
                execution_profile_id=execution_profile_id,
                commit=False,
            )
            if outcome.decision_id is None:
                raise ValueError("live submission requires a valid decision_id")
            existing_link = conn.execute(
                "SELECT reasoning_run_id FROM reasoning_run_decisions WHERE decision_id = ?",
                (outcome.decision_id,),
            ).fetchone()
            if existing_link is not None and existing_link[0] != reasoning_run_id:
                raise ValueError("decision is linked to another reasoning run")
            conn.execute(
                """
                INSERT OR IGNORE INTO reasoning_run_decisions (reasoning_run_id, decision_id)
                VALUES (?, ?)
                """,
                (reasoning_run_id, outcome.decision_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    else:
        outcome = process_decision(
            conn,
            record_data,
            portfolio,
            true_regime_state,
            execution_mode=execution_mode,
            execution_profile_id=execution_profile_id,
        )
    if consume_trigger_ids and outcome.final_status in _CONSIDERED_STATUSES:
        mark_triggers(conn, consume_trigger_ids, "consumed")
    return outcome


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.reason.run")
    parser.add_argument("--db", default="data/boustrategy.db")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--date")
    prepare_parser.add_argument("--out", required=True)
    prepare_parser.add_argument("--digest-dir", default="data/digests")
    prepare_parser.add_argument("--watchlist", default="docs/watchlist.md")

    intake_parser = subparsers.add_parser("intake")
    intake_parser.add_argument("--date")
    intake_parser.add_argument("--out", required=True)

    live_prepare_parser = subparsers.add_parser("prepare-live")
    live_prepare_parser.add_argument("--date")
    live_prepare_parser.add_argument("--slot", required=True)
    live_prepare_parser.add_argument("--out", required=True)
    live_prepare_parser.add_argument("--runs", required=True)
    live_prepare_parser.add_argument("--digest-dir", default="data/digests")

    complete_parser = subparsers.add_parser("complete-live")
    complete_parser.add_argument("--in", dest="input_path", required=True)

    submit_parser = subparsers.add_parser("submit")
    submit_parser.add_argument("--in", dest="input_path", required=True)
    submit_parser.add_argument("--date")
    submit_parser.add_argument("--consume-triggers")
    submit_parser.add_argument("--execution-profile")
    submit_parser.add_argument("--live-profiles", default="ops/live.local.json")
    submit_parser.add_argument("--reasoning-run")

    args = parser.parse_args()
    conn = connect(args.db)
    on_date = date.fromisoformat(args.date) if args.date else date.today()
    if args.command == "prepare":
        result = prepare_session(
            conn,
            on_date,
            args.out,
            digest_dir=args.digest_dir,
            watchlist_path=args.watchlist,
        )
        print(result.model_dump_json())
    elif args.command == "intake":
        print(build_intake(conn, on_date, args.out))
    elif args.command == "prepare-live":
        payload = json.loads(Path(args.runs).read_text(encoding="utf-8"))
        profiles = [
            (
                item["execution_profile_id"],
                item["model_label"],
                item["portfolio_snapshot_id"],
            )
            for item in payload
        ]
        runs = prepare_live_runs(
            conn,
            on_date,
            args.slot,
            args.out,
            profiles,
            digest_dir=args.digest_dir,
        )
        print(json.dumps({"runs": [run.model_dump(mode="json") for run in runs]}))
    elif args.command == "complete-live":
        run = ReasoningRun.model_validate_json(Path(args.input_path).read_text(encoding="utf-8"))
        completed = complete_reasoning_run(conn, run)
        print(
            json.dumps(
                {
                    "reasoning_run_id": completed.reasoning_run_id,
                    "result": completed.result.value,
                    "decision_ids": completed.decision_ids,
                }
            )
        )
    else:
        record_data = json.loads(Path(args.input_path).read_text(encoding="utf-8"))
        trigger_ids = args.consume_triggers.split(",") if args.consume_triggers else []
        execution_mode = ExecutionMode.PAPER
        execution_profile_id = ""
        profile = None
        if args.execution_profile:
            config = load_live_profiles(args.live_profiles)
            profile = get_live_profile(config, args.execution_profile)
            if not profile.enabled:
                raise ValueError(f"execution profile {profile.execution_profile_id} is disabled")
            execution_mode = ExecutionMode.LIVE
            execution_profile_id = profile.execution_profile_id
            if not args.reasoning_run:
                raise ValueError("live submit requires --reasoning-run")
        outcome = submit_decision(
            conn,
            record_data,
            on_date,
            trigger_ids,
            execution_mode=execution_mode,
            execution_profile_id=execution_profile_id,
            reasoning_run_id=args.reasoning_run or "",
            execution_profile=profile,
        )
        print(outcome.model_dump_json())


if __name__ == "__main__":
    main()
