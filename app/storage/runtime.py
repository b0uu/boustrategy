"""Transactional runtime leases. Public readers never call this module."""

import hashlib
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from app.schemas.reasoning_run import ReasoningRun, ReasoningRunResult
from app.schemas.runtime import RuntimeAttempt, RuntimeRun
from app.storage.records import complete_reasoning_run, get_reasoning_run
from app.x.calendar import NEW_YORK, is_session

_ATTEMPT_FIELDS = tuple(RuntimeAttempt.model_fields)


class LeaseLost(ValueError):
    pass


@contextmanager
def immediate(conn: sqlite3.Connection) -> Iterator[None]:
    if conn.in_transaction:
        raise ValueError("runtime operation requires an idle connection")
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()


def save_run(conn: sqlite3.Connection, run: RuntimeRun) -> str:
    if not is_session(run.session_date) and run.origin == "scheduled":
        raise ValueError("reasoning run requires an eligible session")
    if run.prepared_at.astimezone(NEW_YORK).date() != run.session_date:
        raise ValueError("prepared run session does not match local preparation day")
    if Path(run.intake_path).stat().st_size > 512_000:
        raise ValueError("intake_too_large")
    if hashlib.sha256(Path(run.intake_path).read_bytes()).hexdigest() != run.intake_sha256:
        raise ValueError("prepared intake hash mismatch")
    for trigger_id in run.trigger_ids:
        if (
            conn.execute(
                "SELECT 1 FROM trigger_events WHERE trigger_id=?", (trigger_id,)
            ).fetchone()
            is None
        ):
            raise ValueError("event run references an unknown trigger")
    if run.mode == "live":
        legacy = get_reasoning_run(conn, run.reasoning_run_id or "")
        if (
            legacy is None
            or legacy.execution_profile_id != run.execution_profile_id
            or legacy.session_date != run.session_date
            or legacy.slot != run.slot
        ):
            raise ValueError("runtime run does not match prepared reasoning identity")
        snapshot = conn.execute(
            "SELECT snapshot_json FROM live_portfolio_snapshots WHERE portfolio_snapshot_id=?",
            (legacy.portfolio_snapshot_id,),
        ).fetchone()
        from app.schemas.live_execution import LivePortfolioSnapshot

        if (
            snapshot is None
            or LivePortfolioSnapshot.model_validate_json(snapshot[0]).broker_account_fingerprint
            != run.account_id
        ):
            raise ValueError("runtime account does not match prepared snapshot")
    with immediate(conn):
        existing = conn.execute(
            "SELECT public_id, run_json FROM runtime_runs WHERE run_id=?", (run.run_id,)
        ).fetchone()
        if existing:
            if RuntimeRun.model_validate_json(existing[1]) != run:
                raise ValueError("runtime run is immutable")
            return str(existing[0])
        if run.reasoning_run_id:
            legacy = get_reasoning_run(conn, run.reasoning_run_id)
            if legacy is None or legacy.result != "PREPARED":
                raise ValueError("completed manual run cannot be wrapped as a new runtime run")
        public_id = "run_" + uuid4().hex
        conn.execute(
            "INSERT INTO runtime_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run.run_id,
                public_id,
                f"{run.mode}/{run.account_id}",
                run.mode,
                run.account_id,
                run.execution_profile_id,
                run.session_date.isoformat(),
                run.slot,
                run.prepared_at.isoformat(),
                run.reasoning_run_id,
                run.occurrence_id,
                run.model_dump_json(),
            ),
        )
        return public_id


def get_run(conn: sqlite3.Connection, run_id: str) -> RuntimeRun:
    row = conn.execute("SELECT run_json FROM runtime_runs WHERE run_id=?", (run_id,)).fetchone()
    if row is None:
        raise ValueError("runtime run not found")
    return RuntimeRun.model_validate_json(row[0])


def get_attempt(conn: sqlite3.Connection, attempt_id: str) -> RuntimeAttempt:
    row = conn.execute(
        "SELECT * FROM runtime_attempts WHERE attempt_id=?", (attempt_id,)
    ).fetchone()
    if row is None:
        raise ValueError("runtime attempt not found")
    return RuntimeAttempt.model_validate(dict(zip(_ATTEMPT_FIELDS, row, strict=True)))


def expire(conn: sqlite3.Connection, now: datetime) -> int:
    if not conn.in_transaction:
        raise ValueError("expiry requires a write transaction")
    rows = conn.execute(
        "SELECT attempt_id FROM runtime_leases WHERE attempt_id IS NOT "
        "NULL AND julianday(expires_at)<=julianday(?)",
        (now.isoformat(),),
    ).fetchall()
    for (attempt_id,) in rows:
        conn.execute(
            "UPDATE runtime_attempts SET status='expired', stage='finished', "
            "finished_at=?, reason='lease_expired' WHERE attempt_id=? AND "
            "status='running'",
            (now.isoformat(), attempt_id),
        )
        conn.execute(
            "UPDATE runtime_leases SET attempt_id=NULL, expires_at=NULL WHERE attempt_id=?",
            (attempt_id,),
        )
    return len(rows)


def validate_fence(
    conn: sqlite3.Connection, attempt_id: str, fence: int, now: datetime
) -> RuntimeAttempt:
    if not conn.in_transaction:
        raise ValueError("fence validation requires the caller's write transaction")
    attempt = get_attempt(conn, attempt_id)
    row = conn.execute(
        "SELECT fence, expires_at FROM runtime_leases WHERE attempt_id=?", (attempt_id,)
    ).fetchone()
    if (
        attempt.status != "running"
        or attempt.fence != fence
        or row is None
        or row[0] != fence
        or datetime.fromisoformat(row[1]) <= now
    ):
        raise LeaseLost("runtime lease is no longer valid")
    return attempt


def claim(
    conn: sqlite3.Connection,
    run_id: str,
    model: str,
    now: datetime,
    *,
    retry: bool = False,
    lease_seconds: int = 120,
) -> RuntimeAttempt:
    if not model.strip() or not 10 <= lease_seconds <= 3600:
        raise ValueError("claim requires model and a lease between 10 and 3600 seconds")
    with immediate(conn):
        expire(conn, now)
        run = get_run(conn, run_id)
        from app.storage.schedules import validate_claim

        validate_claim(conn, run, now, retry=retry)
        if now < run.prepared_at:
            raise ValueError("claim precedes preparation")
        if run.session_date != now.astimezone(NEW_YORK).date():
            raise ValueError("prepared_session_stale")
        scope = f"{run.mode}/{run.account_id}"
        conn.execute(
            "INSERT OR IGNORE INTO runtime_leases(scope_key, fence) VALUES (?, 0)", (scope,)
        )
        lease = conn.execute(
            "SELECT fence, attempt_id FROM runtime_leases WHERE scope_key=?", (scope,)
        ).fetchone()
        if lease[1] is not None:
            raise ValueError("overlap")
        prior = conn.execute(
            "SELECT status, attempt_number FROM runtime_attempts WHERE "
            "run_id=? ORDER BY attempt_number DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        if prior is None and run.reasoning_run_id:
            legacy = get_reasoning_run(conn, run.reasoning_run_id)
            if legacy is None or legacy.result != "PREPARED":
                raise ValueError("prepared reasoning run already completed manually")
        if prior and (not retry or prior[0] in {"completed", "no_action"}):
            raise ValueError("explicit_retry_required_or_run_complete")
        if retry and prior is None:
            raise ValueError("retry_requires_prior_attempt")
        attempt = RuntimeAttempt(
            attempt_id="attempt_" + uuid4().hex,
            public_id="attempt_" + uuid4().hex,
            run_id=run_id,
            attempt_number=prior[1] + 1 if prior else 1,
            fence=lease[0] + 1,
            status="running",
            stage="starting",
            model=model,
            started_at=now,
            heartbeat_at=now,
        )
        conn.execute(
            "INSERT INTO runtime_attempts VALUES (" + ",".join("?" for _ in _ATTEMPT_FIELDS) + ")",
            tuple(attempt.model_dump(mode="json").values()),
        )
        conn.execute(
            "UPDATE runtime_leases SET fence=?, attempt_id=?, expires_at=? WHERE scope_key=?",
            (
                attempt.fence,
                attempt.attempt_id,
                (now + timedelta(seconds=lease_seconds)).isoformat(),
                scope,
            ),
        )
        return attempt


def heartbeat(
    conn: sqlite3.Connection,
    attempt_id: str,
    fence: int,
    now: datetime,
    *,
    stage: str | None = None,
    lease_seconds: int = 120,
) -> RuntimeAttempt:
    if (
        stage not in {None, "starting", "authoring", "validating", "submitting"}
        or not 10 <= lease_seconds <= 3600
    ):
        raise ValueError("invalid heartbeat stage or lease duration")
    with immediate(conn):
        attempt = validate_fence(conn, attempt_id, fence, now)
        if now < attempt.heartbeat_at:
            raise ValueError("heartbeat clock moved backwards")
        conn.execute(
            "UPDATE runtime_attempts SET heartbeat_at=?, stage=? WHERE attempt_id=?",
            (now.isoformat(), stage or attempt.stage, attempt_id),
        )
        conn.execute(
            "UPDATE runtime_leases SET expires_at=? WHERE attempt_id=?",
            ((now + timedelta(seconds=lease_seconds)).isoformat(), attempt_id),
        )
        return get_attempt(conn, attempt_id)


def finish(
    conn: sqlite3.Connection,
    attempt_id: str,
    fence: int,
    now: datetime,
    *,
    status: str,
    reason: str | None = None,
    public_summary: str | None = None,
) -> RuntimeAttempt:
    if status not in {"completed", "no_action", "failed", "blocked", "timed_out", "canceled"}:
        raise ValueError("invalid terminal status")
    allowed_reasons = {
        None,
        "intake_missing",
        "intake_changed",
        "intake_too_large",
        "runner_timeout",
        "runner_failed",
        "subprocess_pipe_cleanup_failed",
        "operator_canceled",
        "invalid_output",
        "insufficient_research",
        "submission_blocked",
        "snapshot_stale",
        "regime_missing",
        "regime_stale",
        "calendar_out_of_coverage",
        "dependency_missing",
    }
    if reason not in allowed_reasons or (public_summary and len(public_summary) > 4000):
        raise ValueError("invalid public completion metadata")
    with immediate(conn):
        attempt = validate_fence(conn, attempt_id, fence, now)
        if now < attempt.heartbeat_at:
            raise ValueError("completion clock moved backwards")
        count = conn.execute(
            "SELECT COUNT(*) FROM decision_records WHERE runtime_attempt_id=?", (attempt_id,)
        ).fetchone()[0]
        if status == "no_action" and count:
            raise ValueError("no-action attempt has saved decisions")
        run = get_run(conn, attempt.run_id)
        if run.reasoning_run_id:
            legacy = get_reasoning_run(conn, run.reasoning_run_id)
            if legacy is not None and legacy.result == ReasoningRunResult.PREPARED:
                decisions = [
                    row[0]
                    for row in conn.execute(
                        "SELECT decision_id FROM reasoning_run_decisions WHERE "
                        "reasoning_run_id=? ORDER BY decision_id",
                        (run.reasoning_run_id,),
                    )
                ]
                result = (
                    ("DECISIONS_AUTHORED" if decisions else "NO_ACTION")
                    if status in {"completed", "no_action"}
                    else "FAILED"
                )
                completed = ReasoningRun.model_validate(
                    {
                        **legacy.model_dump(),
                        "result": result,
                        "completed_at": now,
                        "decision_ids": decisions,
                        "public_summary": public_summary
                        or "The reasoning attempt ended before completion.",
                    }
                )
                complete_reasoning_run(conn, completed, commit=False)
        conn.execute(
            "UPDATE runtime_attempts SET status=?, stage='finished', "
            "finished_at=?, reason=?, public_summary=? WHERE attempt_id=?",
            (status, now.isoformat(), reason, public_summary, attempt_id),
        )
        conn.execute(
            "UPDATE runtime_leases SET attempt_id=NULL, expires_at=NULL WHERE attempt_id=?",
            (attempt_id,),
        )
        return get_attempt(conn, attempt_id)
