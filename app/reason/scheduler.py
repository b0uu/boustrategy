"""Scheduled authoring waits for completed intake; it never collects broker facts."""

import hashlib
import sqlite3
import traceback
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.reason.run import _completed_digest_runs
from app.reason.runtime_prepare import assemble_intake
from app.reason.worker import execute_attempt
from app.schemas.live_execution import ExecutionProfile
from app.schemas.reasoning_run import ReasoningRun
from app.schemas.runtime import RuntimeRun, SchedulerObservation
from app.storage.runtime import immediate
from app.storage.schedules import latest_schedule, observe, record_due


def execute_due(
    conn: sqlite3.Connection,
    schedule_id: str,
    model: str,
    now: datetime,
    *,
    output_dir: Path,
    log_root: Path,
    digest_dir: Path,
    paper_intake: Path | None = None,
    profile: ExecutionProfile | None = None,
    runner: Any = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> list[dict[str, Any]]:
    schedule = latest_schedule(conn, schedule_id)
    if schedule is None:
        raise ValueError("schedule not found")
    observe(
        conn,
        SchedulerObservation(
            schedule_id=schedule_id,
            revision=schedule.revision,
            observed_at=now,
            observer="worker",
            configured=True,
            enabled=schedule.enabled and schedule.schedule_mode == "scheduled",
        ),
    )
    outcomes = []
    for occurrence in record_due(conn, schedule_id, now):
        row = conn.execute(
            "SELECT session_date FROM schedule_occurrences WHERE occurrence_id=?", (occurrence,)
        ).fetchone()
        from datetime import date

        day = date.fromisoformat(row[0])
        try:
            _completed_digest_runs(conn, day, digest_dir / f"{day}.md")
            if schedule.mode == "live":
                raw = conn.execute(
                    "SELECT run_json FROM reasoning_runs WHERE session_date=? AND "
                    "slot=? AND execution_profile_id=? AND result='PREPARED'",
                    (str(day), schedule.slot, schedule.execution_profile_id),
                ).fetchone()
                if raw is None:
                    raise ValueError("prepared live intake missing")
                legacy = ReasoningRun.model_validate_json(raw[0])
                intake, legacy_id = Path(legacy.shared_bundle_path), legacy.reasoning_run_id
                expected_hash = legacy.shared_bundle_sha256
            else:
                if paper_intake is None:
                    raise ValueError("prepared paper intake missing")
                from app.reason.run import PreparationResult

                receipt = PreparationResult.model_validate_json(
                    paper_intake.read_text(encoding="utf-8")
                )
                if receipt.session_date != day or not receipt.completed_digest_runs:
                    raise ValueError("prepared paper intake belongs to another session")
                intake, legacy_id = Path(receipt.bundle_path), None
                expected_hash = None
            if intake.stat().st_size > 512_000:
                raise ValueError("intake_too_large")
            checksum = hashlib.sha256(intake.read_bytes()).hexdigest()
            if expected_hash and checksum != expected_hash:
                raise ValueError("intake_changed")
        except (OSError, ValueError) as error:
            diagnostic = log_root / (
                "schedule_" + hashlib.sha256(schedule_id.encode()).hexdigest()[:24]
            )
            diagnostic.mkdir(parents=True, exist_ok=True)
            (diagnostic / "dependency.txt").write_text(
                "".join(traceback.format_exception(error))[-64000:], encoding="utf-8"
            )
            with immediate(conn):
                conn.execute(
                    "UPDATE schedule_occurrences SET reason='dependency_missing', "
                    "observed_at=? WHERE occurrence_id=? AND status='waiting'",
                    (now.isoformat(), occurrence),
                )
            outcomes.append({"status": "waiting", "reason": "dependency_missing"})
            continue
        overlap = conn.execute(
            "SELECT 1 FROM runtime_leases WHERE scope_key=? AND attempt_id IS "
            "NOT NULL AND julianday(expires_at)>julianday(?)",
            (f"{schedule.mode}/{schedule.account_id}", now.isoformat()),
        ).fetchone()
        if overlap:
            with immediate(conn):
                conn.execute(
                    "UPDATE schedule_occurrences SET status='skipped', "
                    "reason='overlap', observed_at=? WHERE occurrence_id=? AND "
                    "status='waiting'",
                    (now.isoformat(), occurrence),
                )
            outcomes.append({"status": "skipped", "reason": "overlap"})
            continue
        run = RuntimeRun(
            run_id="runtime_" + uuid4().hex,
            mode=schedule.mode,
            account_id=schedule.account_id,
            execution_profile_id=schedule.execution_profile_id,
            session_date=day,
            slot=schedule.slot,
            prepared_at=now,
            intake_path=str(intake.resolve()),
            intake_sha256=checksum,
            reasoning_run_id=legacy_id,
            occurrence_id=occurrence,
            origin="scheduled",
        )
        existing = conn.execute(
            "SELECT run_json FROM runtime_runs WHERE occurrence_id=?", (occurrence,)
        ).fetchone()
        if existing:
            prepared = RuntimeRun.model_validate_json(existing[0])
        else:
            try:
                prepared = assemble_intake(conn, run, output_dir, profile)
            except sqlite3.IntegrityError:
                winner = conn.execute(
                    "SELECT run_json FROM runtime_runs WHERE occurrence_id=?", (occurrence,)
                ).fetchone()
                if winner is None:
                    raise
                prepared = RuntimeRun.model_validate_json(winner[0])
        options = {"runner": runner} if runner else {}
        try:
            attempt = execute_attempt(
                conn,
                prepared.run_id,
                model,
                log_root=log_root,
                profile=profile,
                clock=clock,
                **options,
            )
        except ValueError as error:
            if str(error) not in {
                "overlap",
                "explicit_retry_required_or_run_complete",
                "occurrence_not_eligible",
            }:
                raise
            outcomes.append(
                {"run_id": prepared.run_id, "status": "not_claimed", "reason": str(error)}
            )
        else:
            outcomes.append({"run_id": prepared.run_id, "status": attempt.status})
    return outcomes
