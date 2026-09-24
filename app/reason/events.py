"""Event reviews: an in-session review started because something happened, not by the clock.

A check rides the 15-minute valuation tick. Crisis mode switching on, or a holding gaining a
mandatory reason, starts an extra review unless a scheduled one is within 30 minutes, three
already ran today, or the same cause already started one.
"""

import argparse
import hashlib
import json
import sqlite3
from datetime import UTC, datetime, time, timedelta
from functools import partial
from pathlib import Path

from app.broker.collector import DEFAULT_COLLECTOR_MODEL, collect_snapshot, default_codex_home
from app.broker.config import get_live_profile, load_live_profiles
from app.broker.valuation import session_window
from app.reason.run import prepare_live_runs
from app.reason.runtime_prepare import assemble_intake
from app.reason.worker import execute_attempt
from app.schemas.live_execution import LivePortfolioSnapshot
from app.schemas.runtime import RuntimeRun
from app.storage.crisis import crisis_reasons
from app.storage.database import connect
from app.storage.holding_reviews import MANDATORY_REASONS, holdings_due
from app.storage.records import get_live_portfolio_snapshot
from app.triggers.store import insert_trigger, trigger_id
from app.x.calendar import NEW_YORK

EVENT_REVIEWS_PER_DAY = 3
SCHEDULED_SLOTS = (time(10), time(13), time(15))
SLOT_QUIET = timedelta(minutes=30)
# Only reasons that can't wait start a review; a missing range waits for the next scheduled one.
URGENT_REASONS = MANDATORY_REASONS - {"range_missing"}


def event_review_cause(
    conn: sqlite3.Connection, snapshot: LivePortfolioSnapshot, now: datetime
) -> str | None:
    """The cause an event review should start for now, or None when nothing warrants one."""
    local = now.astimezone(NEW_YORK)
    if not session_window(now).open or not time(9, 45) <= local.time() <= time(15, 45):
        return None
    if any(
        abs(local - datetime.combine(local.date(), slot, NEW_YORK)) < SLOT_QUIET
        for slot in SCHEDULED_SLOTS
    ):
        return None
    if conn.execute("SELECT 1 FROM runtime_attempts WHERE status='running'").fetchone():
        return None
    today = local.date()
    started = conn.execute(
        "SELECT COUNT(*) FROM trigger_events WHERE trigger_type='event_review' AND fired_at=?",
        (today.isoformat(),),
    ).fetchone()[0]
    if started >= EVENT_REVIEWS_PER_DAY:
        return None
    crisis = crisis_reasons(conn, snapshot, now)
    causes = (["crisis"] if crisis else []) + [
        f"{holding['ticker']}:{reason}"
        for holding in holdings_due(conn, snapshot, now, crisis=bool(crisis))
        for reason in holding["reasons"]
        if reason in URGENT_REASONS
    ]
    return next(
        (
            cause
            for cause in causes
            if not conn.execute(
                "SELECT 1 FROM trigger_events WHERE trigger_id=?",
                (trigger_id("event_review", cause, today),),
            ).fetchone()
        ),
        None,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/boustrategy.db")
    parser.add_argument("--live-profiles", default="ops/live.local.json")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--collector-model", default=DEFAULT_COLLECTOR_MODEL)
    parser.add_argument("--digest-dir", default="data/digests")
    parser.add_argument("--out", default="data/runtime-intakes")
    parser.add_argument("--logs", default="data/runtime-logs")
    args = parser.parse_args()
    now = datetime.now(UTC)
    profile = get_live_profile(load_live_profiles(args.live_profiles), args.profile)
    conn = connect(args.db, wal=True)
    try:
        latest = conn.execute(
            "SELECT portfolio_snapshot_id FROM live_portfolio_snapshots "
            "WHERE execution_profile_id=? ORDER BY julianday(captured_at) DESC LIMIT 1",
            (profile.execution_profile_id,),
        ).fetchone()
        snapshot = get_live_portfolio_snapshot(conn, latest[0]) if latest else None
        cause = event_review_cause(conn, snapshot, now) if snapshot else None
        if cause is None:
            print(json.dumps({"cause": None}))
            return
        today = now.astimezone(NEW_YORK).date()
        insert_trigger(conn, "event_review", cause, today, today, {"cause": cause})
        count = conn.execute(
            "SELECT COUNT(*) FROM trigger_events WHERE trigger_type='event_review' AND fired_at=?",
            (today.isoformat(),),
        ).fetchone()[0]
        slot = f"event-{count}"
        collector = partial(
            collect_snapshot,
            conn,
            profile,
            model=args.collector_model,
            codex_home=default_codex_home(),
            log_dir=Path(args.logs) / "collector",
        )
        fresh = collector()
        legacy = prepare_live_runs(
            conn,
            today,
            slot,
            Path("data/reason_runs") / f"{today}-live-{slot}",
            [(profile.execution_profile_id, args.model, fresh.portfolio_snapshot_id)],
            digest_dir=args.digest_dir,
        )[0]
        intake = Path(legacy.shared_bundle_path)
        run = RuntimeRun(
            run_id=f"runtime_{legacy.reasoning_run_id}",
            mode="live",
            account_id=profile.broker_account_fingerprint,
            execution_profile_id=profile.execution_profile_id,
            session_date=today,
            slot=slot,
            prepared_at=datetime.now(UTC),
            intake_path=str(intake.resolve()),
            intake_sha256=hashlib.sha256(intake.read_bytes()).hexdigest(),
            reasoning_run_id=legacy.reasoning_run_id,
            origin="event",
            trigger_ids=[trigger_id("event_review", cause, today)],
        )
        prepared = assemble_intake(conn, run, Path(args.out), profile)
        attempt = execute_attempt(
            conn,
            prepared.run_id,
            args.model,
            log_root=Path(args.logs),
            profile=profile,
            snapshot_collector=collector,
        )
        print(json.dumps({"cause": cause, "slot": slot, "attempt": attempt.status}))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
