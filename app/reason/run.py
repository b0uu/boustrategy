import argparse
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
from app.regime.run import latest_published_regime, score_date
from app.schemas.decision_record import RegimeState
from app.schemas.order_intent import ExecutionMode
from app.state.pipeline import DecisionStatus, ProcessOutcome, process_decision
from app.storage.database import connect
from app.triggers.evaluate import evaluate_triggers
from app.triggers.store import mark_triggers

from .intake import build_intake

_CONSIDERED_STATUSES = {
    DecisionStatus.POLICY_APPROVED,
    DecisionStatus.POLICY_REJECTED,
    DecisionStatus.ORDER_INTENT_CREATED,
}


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


def submit_decision(
    conn: sqlite3.Connection,
    record_data: dict[str, Any],
    on_date: date,
    consume_trigger_ids: list[str] | None = None,
    *,
    execution_mode: ExecutionMode = ExecutionMode.PAPER,
    execution_profile_id: str = "",
) -> ProcessOutcome:
    raw_ticker = record_data.get("ticker")
    ticker = raw_ticker if isinstance(raw_ticker, str) else None
    portfolio = portfolio_context(conn, on_date, exclude_ticker=ticker)
    true_regime_state = latest_published_regime(conn, on_date)
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

    submit_parser = subparsers.add_parser("submit")
    submit_parser.add_argument("--in", dest="input_path", required=True)
    submit_parser.add_argument("--date")
    submit_parser.add_argument("--consume-triggers")
    submit_parser.add_argument("--execution-profile")
    submit_parser.add_argument("--live-profiles", default="ops/live.local.json")

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
    else:
        record_data = json.loads(Path(args.input_path).read_text(encoding="utf-8"))
        trigger_ids = args.consume_triggers.split(",") if args.consume_triggers else []
        execution_mode = ExecutionMode.PAPER
        execution_profile_id = ""
        if args.execution_profile:
            config = load_live_profiles(args.live_profiles)
            profile = get_live_profile(config, args.execution_profile)
            if not profile.enabled:
                raise ValueError(f"execution profile {profile.execution_profile_id} is disabled")
            execution_mode = ExecutionMode.LIVE
            execution_profile_id = profile.execution_profile_id
        outcome = submit_decision(
            conn,
            record_data,
            on_date,
            trigger_ids,
            execution_mode=execution_mode,
            execution_profile_id=execution_profile_id,
        )
        print(outcome.model_dump_json())


if __name__ == "__main__":
    main()
