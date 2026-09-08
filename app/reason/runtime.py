"""Private runtime controls. Configuration and preview never start a model."""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.broker.config import get_live_profile, load_live_profiles
from app.public.database import open_readonly
from app.reason.runtime_prepare import assemble_intake
from app.reason.worker import execute_attempt
from app.schemas.runtime import RuntimeRun, ScheduleRevision, SchedulerObservation
from app.storage.database import connect
from app.storage.records import get_reasoning_run
from app.storage.runtime import expire, finish, get_attempt, get_run, immediate
from app.storage.schedules import (
    latest_schedule,
    observe,
    planned_preview,
    record_due,
    save_schedule,
)
from app.x.calendar import NEW_YORK


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/boustrategy.db")
    parser.add_argument("--live-profiles", default="ops/live.local.json")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--intake")
    prepare.add_argument("--reasoning-run")
    prepare.add_argument("--out", required=True)
    prepare.add_argument("--run-id")
    prepare.add_argument("--slot", default="manual")
    prepare.add_argument("--occurrence")
    prepare.add_argument("--trigger", action="append", default=[])
    for command in ("start", "retry"):
        runner = sub.add_parser(command)
        runner.add_argument("--run", required=True)
        runner.add_argument("--model", required=True)
        runner.add_argument("--logs", default="data/runtime-logs")
        runner.add_argument("--timeout", type=float, default=1800)
    cancel = sub.add_parser("cancel")
    cancel.add_argument("--attempt", required=True)
    sub.add_parser("reconcile")
    configure = sub.add_parser("configure")
    configure.add_argument("--in", dest="input", required=True)
    for command in ("pause", "resume", "preview", "due"):
        schedule_parser = sub.add_parser(command)
        schedule_parser.add_argument("--schedule", required=True)
    observer = sub.add_parser("observe")
    observer.add_argument("--in", dest="input", required=True)
    scheduled = sub.add_parser("scheduled")
    scheduled.add_argument("--schedule", required=True)
    scheduled.add_argument("--model", required=True)
    scheduled.add_argument("--out", default="data/runtime-intakes")
    scheduled.add_argument("--logs", default="data/runtime-logs")
    scheduled.add_argument("--digest-dir", default="data/digests")
    scheduled.add_argument("--paper-preparation")
    args = parser.parse_args()
    now = datetime.now(UTC)
    if args.command == "preview":
        with open_readonly(args.db, allow_wal=True) as conn:
            schedule = latest_schedule(conn, args.schedule)
            if schedule is None:
                raise ValueError("schedule not found")
            print(json.dumps(planned_preview(schedule, now)))
        return
    conn = connect(args.db, wal=True)
    try:
        if args.command == "prepare":
            profile = None
            legacy = get_reasoning_run(conn, args.reasoning_run) if args.reasoning_run else None
            if args.reasoning_run and legacy is None:
                raise ValueError("prepared reasoning run not found")
            if legacy:
                profile = get_live_profile(
                    load_live_profiles(args.live_profiles), legacy.execution_profile_id
                )
                intake = Path(legacy.shared_bundle_path)
                slot = legacy.slot
            else:
                if not args.intake:
                    raise ValueError("paper preparation requires --intake")
                intake, slot = Path(args.intake), args.slot
            if intake.stat().st_size > 512_000:
                raise ValueError("intake_too_large")
            run = RuntimeRun(
                run_id=args.run_id or "runtime_" + uuid4().hex,
                mode="live" if legacy else "paper",
                account_id=profile.broker_account_fingerprint if profile else "paper",
                execution_profile_id=profile.execution_profile_id if profile else "",
                session_date=now.astimezone(NEW_YORK).date(),
                slot=slot,
                prepared_at=now,
                intake_path=str(intake.resolve()),
                intake_sha256=hashlib.sha256(intake.read_bytes()).hexdigest(),
                reasoning_run_id=legacy.reasoning_run_id if legacy else None,
                occurrence_id=args.occurrence,
                origin="scheduled" if args.occurrence else "event" if args.trigger else "manual",
                trigger_ids=args.trigger,
            )
            prepared = assemble_intake(conn, run, Path(args.out), profile)
            print(
                json.dumps(
                    {
                        "run_id": prepared.run_id,
                        "status": "prepared",
                        "intake_path": prepared.intake_path,
                    }
                )
            )
        elif args.command in {"start", "retry"}:
            run = get_run(conn, args.run)
            profile = (
                get_live_profile(load_live_profiles(args.live_profiles), run.execution_profile_id)
                if run.mode == "live"
                else None
            )
            attempt = execute_attempt(
                conn,
                run.run_id,
                args.model,
                log_root=Path(args.logs),
                profile=profile,
                retry=args.command == "retry",
                timeout_seconds=args.timeout,
            )
            print(attempt.model_dump_json())
        elif args.command == "scheduled":
            from app.reason.scheduler import execute_due

            schedule = latest_schedule(conn, args.schedule)
            if schedule is None:
                raise ValueError("schedule not found")
            profile = (
                get_live_profile(
                    load_live_profiles(args.live_profiles), schedule.execution_profile_id
                )
                if schedule.mode == "live"
                else None
            )
            print(
                json.dumps(
                    execute_due(
                        conn,
                        args.schedule,
                        args.model,
                        now,
                        output_dir=Path(args.out),
                        log_root=Path(args.logs),
                        digest_dir=Path(args.digest_dir),
                        profile=profile,
                        paper_intake=Path(args.paper_preparation)
                        if args.paper_preparation
                        else None,
                    )
                )
            )
        elif args.command == "cancel":
            attempt = get_attempt(conn, args.attempt)
            print(
                finish(
                    conn,
                    attempt.attempt_id,
                    attempt.fence,
                    now,
                    status="canceled",
                    reason="operator_canceled",
                ).model_dump_json()
            )
        elif args.command == "reconcile":
            with immediate(conn):
                print(json.dumps({"expired_attempts": expire(conn, now)}))
        elif args.command == "observe":
            observation = SchedulerObservation.model_validate_json(
                Path(args.input).read_text(encoding="utf-8")
            )
            observe(conn, observation)
            print(json.dumps({"status": "observed", "revision": observation.revision}))
        elif args.command == "due":
            print(json.dumps({"occurrences": record_due(conn, args.schedule, now)}))
        else:
            if args.command == "configure":
                schedule = ScheduleRevision.model_validate_json(
                    Path(args.input).read_text(encoding="utf-8")
                )
            else:
                previous = latest_schedule(conn, args.schedule)
                if previous is None:
                    raise ValueError("schedule not found")
                schedule = previous.model_copy(
                    update={
                        "revision": previous.revision + 1,
                        "configured_at": now,
                        "paused": args.command == "pause",
                    }
                )
            profile = (
                get_live_profile(
                    load_live_profiles(args.live_profiles), schedule.execution_profile_id
                )
                if schedule.mode == "live"
                else None
            )
            save_schedule(conn, schedule, profile)
            print(
                json.dumps(
                    {
                        "status": "configured",
                        "revision": schedule.revision,
                        "enabled": schedule.enabled,
                        "paused": schedule.paused,
                    }
                )
            )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
