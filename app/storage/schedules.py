"""One persisted schedule authority shared by preview, worker and publication."""

import sqlite3
from datetime import date, datetime, timedelta
from typing import Any
from uuid import uuid4

from app.schemas.live_execution import ExecutionProfile
from app.schemas.runtime import RuntimeRun, ScheduleRevision, SchedulerObservation
from app.storage.runtime import immediate
from app.x.calendar import COVERAGE_END, NEW_YORK, CalendarCoverageError, session_close


def save_schedule(
    conn: sqlite3.Connection, record: ScheduleRevision, profile: ExecutionProfile | None = None
) -> None:
    if record.mode == "live" and (
        profile is None
        or profile.execution_profile_id != record.execution_profile_id
        or profile.broker_account_fingerprint != record.account_id
    ):
        raise ValueError("schedule requires its account-bound execution profile")
    with immediate(conn):
        previous = latest_schedule(conn, record.schedule_id)
        if previous == record:
            return
        if record.revision != (previous.revision + 1 if previous else 1):
            raise ValueError("schedule revision must follow the current revision")
        if previous and (previous.mode, previous.account_id, previous.execution_profile_id) != (
            record.mode,
            record.account_id,
            record.execution_profile_id,
        ):
            raise ValueError("schedule cannot change account identity")
        if previous and previous.configured_at > record.configured_at:
            raise ValueError("schedule revision precedes its predecessor")
        conn.execute(
            "INSERT INTO schedule_revisions VALUES (?, ?, ?, ?)",
            (
                record.schedule_id,
                record.revision,
                f"{record.mode}/{record.account_id}",
                record.model_dump_json(),
            ),
        )
        waiting = conn.execute(
            "SELECT occurrence_id, session_date FROM schedule_occurrences "
            "WHERE schedule_id=? AND status='waiting'",
            (record.schedule_id,),
        ).fetchall()
        for occurrence_id, session_date in waiting:
            due = due_at(record, date.fromisoformat(session_date))
            conn.execute(
                "UPDATE schedule_occurrences SET revision=?, due_at=COALESCE(?, "
                "due_at), status=?, reason=?, observed_at=? WHERE occurrence_id=?",
                (
                    record.revision,
                    due.isoformat() if due else None,
                    "waiting" if due else "skipped",
                    "schedule_ineligible"
                    if due is None
                    else "paused"
                    if record.paused
                    else "schedule_revised",
                    record.configured_at.isoformat(),
                    occurrence_id,
                ),
            )


def latest_schedule(conn: sqlite3.Connection, schedule_id: str) -> ScheduleRevision | None:
    row = conn.execute(
        "SELECT record_json FROM schedule_revisions WHERE schedule_id=? "
        "ORDER BY revision DESC LIMIT 1",
        (schedule_id,),
    ).fetchone()
    return ScheduleRevision.model_validate_json(row[0]) if row else None


def observe(conn: sqlite3.Connection, observation: SchedulerObservation) -> None:
    with immediate(conn):
        schedule = latest_schedule(conn, observation.schedule_id)
        if schedule is None or schedule.revision != observation.revision:
            raise ValueError("observer refers to a different schedule revision")
        previous = conn.execute(
            "SELECT observed_at FROM scheduler_observations WHERE schedule_id=?",
            (observation.schedule_id,),
        ).fetchone()
        if previous and datetime.fromisoformat(previous[0]) > observation.observed_at:
            raise ValueError("observer clock moved backwards")
        conn.execute(
            "INSERT INTO scheduler_observations VALUES (?, ?, ?, ?) ON "
            "CONFLICT(schedule_id) DO UPDATE SET revision=excluded.revision, "
            "observed_at=excluded.observed_at, record_json=excluded.record_json",
            (
                observation.schedule_id,
                observation.revision,
                observation.observed_at.isoformat(),
                observation.model_dump_json(),
            ),
        )


def authority_reason(
    conn: sqlite3.Connection, schedule: ScheduleRevision, now: datetime
) -> str | None:
    if schedule.paused:
        return "paused"
    if schedule.schedule_mode == "manual":
        return "manual"
    if not schedule.enabled:
        return "schedule_disabled"
    row = conn.execute(
        "SELECT record_json FROM scheduler_observations WHERE schedule_id=?",
        (schedule.schedule_id,),
    ).fetchone()
    if row is None:
        return "observer_missing"
    observation = SchedulerObservation.model_validate_json(row[0])
    age = (now - observation.observed_at).total_seconds()
    if (
        observation.revision != schedule.revision
        or age < 0
        or age > schedule.observer_max_age_seconds
    ):
        return "observer_stale"
    if not observation.configured or not observation.enabled:
        return "observer_disabled"
    return None


def due_at(schedule: ScheduleRevision, session: date) -> datetime | None:
    close = session_close(session)
    if close is None:
        return None
    local = schedule.early_close_due_local if close.hour == 13 else schedule.due_local
    return datetime.combine(session, local, NEW_YORK) if local is not None else None


def preview(conn: sqlite3.Connection, schedule: ScheduleRevision, now: datetime) -> dict[str, Any]:
    reason = authority_reason(conn, schedule, now)
    result: dict[str, Any] = {
        "schedule_mode": schedule.schedule_mode,
        "timezone": schedule.timezone,
        "revision": schedule.revision,
        "enabled": schedule.enabled,
        "paused": schedule.paused,
        "next_due_at": None,
        "reason": reason,
        "as_of": now.isoformat(),
    }
    row = conn.execute(
        "SELECT observed_at FROM scheduler_observations WHERE schedule_id=?",
        (schedule.schedule_id,),
    ).fetchone()
    result["observer_as_of"] = row[0] if row else None
    if reason:
        return result
    day = now.astimezone(NEW_YORK).date()
    try:
        while day <= COVERAGE_END:
            due = due_at(schedule, day)
            occurrence = conn.execute(
                "SELECT status FROM schedule_occurrences WHERE schedule_id=? AND session_date=?",
                (schedule.schedule_id, day.isoformat()),
            ).fetchone()
            if (
                due
                and due >= schedule.configured_at
                and now <= due + timedelta(seconds=schedule.grace_seconds)
                and (occurrence is None or occurrence[0] == "waiting")
            ):
                result["next_due_at"] = due.isoformat()
                result["reason"] = "due" if due <= now else None
                return result
            day += timedelta(days=1)
    except CalendarCoverageError:
        pass
    result["reason"] = "calendar_out_of_coverage"
    return result


def record_due(conn: sqlite3.Connection, schedule_id: str, now: datetime) -> list[str]:
    with immediate(conn):
        schedule = latest_schedule(conn, schedule_id)
        if schedule is None:
            raise ValueError("schedule not found")
        reason = authority_reason(conn, schedule, now)
        if reason:
            return []
        last = conn.execute(
            "SELECT MAX(session_date) FROM schedule_occurrences WHERE schedule_id=?", (schedule_id,)
        ).fetchone()[0]
        day = (
            date.fromisoformat(last) if last else schedule.configured_at.astimezone(NEW_YORK).date()
        )
        ready = []
        while day <= now.astimezone(NEW_YORK).date():
            due = due_at(schedule, day)
            if due is not None and schedule.configured_at <= due <= now:
                # Runs must be prepared and claimed on their own ET session day.
                expired = now > due + timedelta(seconds=schedule.grace_seconds) or (
                    now.astimezone(NEW_YORK).date() > day
                )
                identity = "occ_" + uuid4().hex
                conn.execute(
                    "INSERT OR IGNORE INTO schedule_occurrences VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        identity,
                        "occ_" + uuid4().hex,
                        schedule_id,
                        schedule.revision,
                        day.isoformat(),
                        due.isoformat(),
                        "skipped" if expired else "waiting",
                        "grace_expired" if expired else None,
                        now.isoformat(),
                    ),
                )
                row = conn.execute(
                    "SELECT occurrence_id, status FROM schedule_occurrences WHERE "
                    "schedule_id=? AND session_date=?",
                    (schedule_id, day.isoformat()),
                ).fetchone()
                if row[1] == "waiting":
                    if expired:
                        conn.execute(
                            "UPDATE schedule_occurrences SET status='skipped', "
                            "reason='grace_expired', observed_at=? WHERE occurrence_id=?",
                            (now.isoformat(), row[0]),
                        )
                    else:
                        ready.append(row[0])
            day += timedelta(days=1)
        return ready


def validate_claim(
    conn: sqlite3.Connection, run: RuntimeRun, now: datetime, *, retry: bool = False
) -> None:
    schedules = conn.execute(
        "SELECT s.record_json FROM schedule_revisions s WHERE scope_key=? "
        "AND revision=(SELECT MAX(n.revision) FROM schedule_revisions n "
        "WHERE n.schedule_id=s.schedule_id)",
        (f"{run.mode}/{run.account_id}",),
    ).fetchall()
    if any(ScheduleRevision.model_validate_json(row[0]).paused for row in schedules):
        raise ValueError("paused")
    if run.origin != "scheduled":
        return
    row = conn.execute(
        "SELECT schedule_id, revision, session_date, due_at, status FROM "
        "schedule_occurrences WHERE occurrence_id=?",
        (run.occurrence_id,),
    ).fetchone()
    if row is None:
        raise ValueError("scheduled_run_requires_occurrence")
    schedule = latest_schedule(conn, row[0])
    if (
        schedule is None
        or (schedule.revision != row[1] and row[4] != "claimed")
        or schedule.mode != run.mode
        or schedule.account_id != run.account_id
        or schedule.execution_profile_id != run.execution_profile_id
        or run.session_date.isoformat() != row[2]
        or run.slot != schedule.slot
    ):
        raise ValueError("schedule_occurrence_identity_mismatch")
    reason = authority_reason(conn, schedule, now)
    if reason:
        raise ValueError(reason)
    if due_at(schedule, run.session_date) is None:
        raise ValueError("occurrence_not_eligible")
    due = datetime.fromisoformat(row[3])
    if row[4] not in {"waiting", "claimed"} or (
        not (retry and row[4] == "claimed")
        and not due <= now <= due + timedelta(seconds=schedule.grace_seconds)
    ):
        raise ValueError("occurrence_not_eligible")
    conn.execute(
        "UPDATE schedule_occurrences SET status='claimed', observed_at=? WHERE occurrence_id=?",
        (now.isoformat(), run.occurrence_id),
    )


def planned_preview(schedule: ScheduleRevision, now: datetime, limit: int = 10) -> dict[str, Any]:
    if not 1 <= limit <= 100:
        raise ValueError("preview limit must be 1 through 100")
    day = now.astimezone(NEW_YORK).date()
    items: list[dict[str, str]] = []
    while day <= COVERAGE_END and len(items) < limit:
        due = due_at(schedule, day)
        if due and due >= now:
            items.append(
                {"session_date": day.isoformat(), "due_at": due.isoformat(), "status": "planned"}
            )
        day += timedelta(days=1)
    return {
        "revision": schedule.revision,
        "enabled": schedule.enabled,
        "paused": schedule.paused,
        "timezone": schedule.timezone,
        "items": items,
        "authority": "planned_not_observed",
    }
