"""Sanitized runtime activity, materialized only by the trusted publisher."""

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from app.dashboard.queries import table_exists
from app.schemas.reasoning_run import ReasoningRun
from app.schemas.runtime import RuntimeRun, ScheduleRevision
from app.storage.schedules import preview

_SCHEMA = """
CREATE TABLE IF NOT EXISTS public_activity (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT, source_key TEXT NOT NULL UNIQUE,
    public_id TEXT NOT NULL UNIQUE, portfolio_id TEXT NOT NULL, created_at TEXT NOT NULL,
    content TEXT NOT NULL, feed_content TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS activity_scope ON public_activity
    (portfolio_id, created_at DESC, public_id DESC);
CREATE TABLE IF NOT EXISTS activity_meta (singleton INTEGER PRIMARY KEY, revision INTEGER NOT NULL);
INSERT OR IGNORE INTO activity_meta VALUES (1, 0);
CREATE INDEX IF NOT EXISTS activity_status ON public_activity
    (portfolio_id, json_extract(content, '$.status'), created_at DESC);
CREATE TABLE IF NOT EXISTS public_run_ids (
    source_key TEXT PRIMARY KEY, public_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS public_runtime (
    portfolio_id TEXT PRIMARY KEY, content TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS publication_checkpoint (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1), content TEXT NOT NULL
);
"""


def publish_activity(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    live_profiles: tuple[str, ...],
    now: datetime,
    *,
    since: int | None = None,
) -> None:
    target.execute("UPDATE activity_meta SET revision=revision+1")
    clauses = {
        kind: ""
        if since is None
        else (
            f" WHERE {column} IN (SELECT source_id FROM publication_activity_changes "
            f"WHERE kind='{kind}' AND revision>{since})"
        )
        for kind, column in (
            ("runtime", "run_id"),
            ("legacy", "reasoning_run_id"),
            ("occurrence", "occurrence_id"),
        )
    }
    seen: set[str] = set()
    changed = (
        source.execute(
            "SELECT kind, source_id FROM publication_activity_changes WHERE revision>?", (since,)
        ).fetchall()
        if since is not None
        else []
    )
    for kind, source_id in changed:
        key = "occurrence/" + source_id if kind == "occurrence" else source_id
        seen.add(hashlib.sha256(key.encode()).hexdigest())
    materialized: set[str] = set()
    if table_exists(source, "runtime_runs"):
        attempts_by_run: dict[str, list[dict[str, Any]]] = {}
        counts: dict[str, int] = {}
        query = (
            "SELECT run_id, public_id, attempt_number, status, stage, model, observed_model, "
            "started_at, heartbeat_at, finished_at, reason, public_summary, total FROM "
            "(SELECT *, ROW_NUMBER() OVER (PARTITION BY run_id ORDER BY "
            "attempt_number DESC) AS rank, "
            "COUNT(*) OVER (PARTITION BY run_id) AS total FROM runtime_attempts"
            + clauses["runtime"]
            + ") WHERE rank<=100 ORDER BY run_id, attempt_number DESC"
        )
        for row in source.execute(query):
            counts[row[0]] = row[-1]
            attempts_by_run.setdefault(row[0], []).append(
                dict(
                    zip(
                        (
                            "public_id",
                            "attempt_number",
                            "status",
                            "stage",
                            "requested_model",
                            "observed_model",
                            "started_at",
                            "heartbeat_at",
                            "finished_at",
                            "reason",
                            "summary",
                        ),
                        row[1:-1],
                        strict=True,
                    )
                )
            )
        leases = dict(
            source.execute(
                "SELECT a.public_id, l.expires_at FROM runtime_leases l JOIN "
                "runtime_attempts a USING(attempt_id)"
            )
        )
        for public_id, raw in source.execute(
            "SELECT public_id, run_json FROM runtime_runs"
            + clauses["runtime"]
            + " ORDER BY prepared_at"
        ):
            run = RuntimeRun.model_validate_json(raw)
            if run.mode == "live" and run.execution_profile_id not in live_profiles:
                continue
            if run.reasoning_run_id:
                existing_legacy = target.execute(
                    "SELECT public_id FROM public_run_ids WHERE source_key=?",
                    (hashlib.sha256(run.reasoning_run_id.encode()).hexdigest(),),
                ).fetchone()
                if existing_legacy:
                    public_id = existing_legacy[0]
                target.execute(
                    "DELETE FROM public_activity WHERE source_key=?",
                    (hashlib.sha256(run.reasoning_run_id.encode()).hexdigest(),),
                )
            attempts = attempts_by_run.get(run.run_id, [])
            count = counts.get(run.run_id, 0)
            item = {
                "public_id": public_id,
                "origin": run.origin,
                "session_date": str(run.session_date),
                "slot": run.slot,
                "prepared_at": run.prepared_at.isoformat(),
                "status": attempts[0]["status"] if attempts else "prepared",
                "attempts": attempts,
                "attempt_count": count,
                "attempts_truncated": count > 100,
                "trigger_count": len(run.trigger_ids),
            }
            if attempts and attempts[0]["status"] == "running":
                item["lease_expires_at"] = leases.get(attempts[0]["public_id"])
            _save(target, run.run_id, public_id, run.mode, run.prepared_at, item)
            materialized.add(hashlib.sha256(run.run_id.encode()).hexdigest())
    if table_exists(source, "reasoning_runs"):
        for (raw,) in source.execute(
            "SELECT run_json FROM reasoning_runs"
            + clauses["legacy"]
            + (" AND " if clauses["legacy"] else " WHERE ")
            + (
                "NOT EXISTS (SELECT 1 FROM runtime_runs r WHERE "
                "r.reasoning_run_id=reasoning_runs.reasoning_run_id)"
                if table_exists(source, "runtime_runs")
                else "1=1"
            )
            + " ORDER BY started_at"
        ):
            legacy = ReasoningRun.model_validate_json(raw)
            if legacy.execution_profile_id not in live_profiles:
                continue
            existing = target.execute(
                "SELECT public_id FROM public_activity WHERE source_key=?",
                (hashlib.sha256(legacy.reasoning_run_id.encode()).hexdigest(),),
            ).fetchone()
            public_id = existing[0] if existing else "run_" + uuid4().hex
            item = {
                "public_id": public_id,
                "origin": "manual",
                "session_date": str(legacy.session_date),
                "slot": legacy.slot,
                "prepared_at": legacy.started_at.isoformat(),
                "status": "prepared"
                if legacy.result == "PREPARED"
                else legacy.result.value.lower(),
                "attempts": [],
                "attempt_count": 0,
                "attempts_truncated": False,
                "completed_at": legacy.completed_at.isoformat() if legacy.completed_at else None,
                "summary": legacy.public_summary or None,
                "execution_observation": "manual_completion"
                if legacy.completed_at
                else "not_started",
            }
            _save(target, legacy.reasoning_run_id, public_id, "live", legacy.started_at, item)
            materialized.add(hashlib.sha256(legacy.reasoning_run_id.encode()).hexdigest())
    schedules: dict[str, list[dict[str, Any]]] = {"live": [], "paper": []}
    if table_exists(source, "schedule_revisions"):
        for (raw,) in source.execute(
            "SELECT s.record_json FROM schedule_revisions s WHERE revision="
            "(SELECT MAX(revision) FROM schedule_revisions n WHERE n.schedule_id=s.schedule_id)"
        ):
            schedule = ScheduleRevision.model_validate_json(raw)
            if schedule.mode == "live" and schedule.execution_profile_id not in live_profiles:
                continue
            view = preview(source, schedule, now)
            view["observer_max_age_seconds"] = schedule.observer_max_age_seconds
            view["grace_seconds"] = schedule.grace_seconds
            schedules[schedule.mode].append(view)
        for occurrence_id, public_id, _schedule_id, day, due, status, reason, raw in source.execute(
            "SELECT o.occurrence_id, o.public_id, o.schedule_id, "
            "o.session_date, o.due_at, o.status, o.reason, s.record_json "
            "FROM schedule_occurrences o JOIN schedule_revisions s ON s.schedule_id=o.schedule_id "
            "AND s.revision=(SELECT MAX(n.revision) FROM schedule_revisions n "
            "WHERE n.schedule_id=o.schedule_id) "
            "WHERE o.status='skipped'"
            + (
                " AND o.occurrence_id IN (SELECT source_id FROM "
                "publication_activity_changes WHERE kind='occurrence' AND "
                "revision>?)"
                if since is not None
                else ""
            ),
            (since,) if since is not None else (),
        ):
            schedule = ScheduleRevision.model_validate_json(raw)
            if schedule.mode == "live" and schedule.execution_profile_id not in live_profiles:
                continue
            item = {
                "public_id": public_id,
                "origin": "scheduled",
                "session_date": day,
                "status": status,
                "reason": reason,
                "due_at": due,
                "attempts": [],
                "attempt_count": 0,
                "attempts_truncated": False,
            }
            _save(
                target,
                "occurrence/" + occurrence_id,
                public_id,
                schedule.mode,
                datetime.fromisoformat(due),
                item,
            )
            materialized.add(hashlib.sha256(("occurrence/" + occurrence_id).encode()).hexdigest())
    if since is None:
        seen = {row[0] for row in target.execute("SELECT source_key FROM public_activity")}
    for key in seen - materialized:
        target.execute("DELETE FROM public_activity WHERE source_key=?", (key,))
    for scope in ("live", "paper"):
        latest_row = target.execute(
            "SELECT feed_content FROM public_activity WHERE portfolio_id=? "
            "ORDER BY created_at DESC, public_id DESC LIMIT 1",
            (scope,),
        ).fetchone()
        active_row = target.execute(
            "SELECT feed_content FROM public_activity WHERE portfolio_id=? AND "
            "json_extract(content, '$.status')='running' ORDER BY created_at "
            "DESC LIMIT 1",
            (scope,),
        ).fetchone()
        content = {
            "as_of": now.isoformat(),
            "latest_run": json.loads(latest_row[0]) if latest_row else None,
            "active_run": json.loads(active_row[0]) if active_row else None,
            "schedules": schedules[scope],
            "schedule_mode": "manual" if not schedules[scope] else "recorded",
        }
        target.execute(
            "INSERT INTO public_runtime VALUES (?, ?) ON CONFLICT(portfolio_id) "
            "DO UPDATE SET content=excluded.content",
            (scope, json.dumps(content, sort_keys=True)),
        )


def _save(
    target: sqlite3.Connection,
    source_id: str,
    public_id: str,
    scope: str,
    created_at: datetime,
    content: dict[str, Any],
) -> None:
    source_key = hashlib.sha256(source_id.encode()).hexdigest()
    existing = target.execute(
        "SELECT public_id FROM public_run_ids WHERE source_key=?", (source_key,)
    ).fetchone()
    public_id = existing[0] if existing else public_id
    target.execute("INSERT OR IGNORE INTO public_run_ids VALUES (?, ?)", (source_key, public_id))
    content["public_id"] = public_id
    compact = {key: value for key, value in content.items() if key != "attempts"}
    if compact.get("summary"):
        compact["summary"] = compact["summary"][:600]
    attempts = content.get("attempts", [])
    compact["latest_attempt"] = (
        {**attempts[0], "summary": (attempts[0].get("summary") or "")[:600]} if attempts else None
    )
    target.execute(
        "INSERT INTO public_activity (source_key, public_id, portfolio_id, "
        "created_at, content, feed_content) "
        "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(source_key) DO UPDATE SET "
        "content=excluded.content, feed_content=excluded.feed_content",
        (
            hashlib.sha256(source_id.encode()).hexdigest(),
            public_id,
            scope,
            created_at.astimezone(UTC).isoformat(),
            json.dumps(content, sort_keys=True),
            json.dumps(compact, sort_keys=True),
        ),
    )


def runtime_status(conn: sqlite3.Connection, scope: str, now: datetime) -> dict[str, Any]:
    row = (
        conn.execute("SELECT content FROM public_runtime WHERE portfolio_id=?", (scope,)).fetchone()
        if table_exists(conn, "public_runtime")
        else None
    )
    if row is None:
        return {
            "status": "unavailable",
            "reason": "runtime_not_published",
            "latest_run": None,
            "schedules": [],
        }
    result: dict[str, Any] = json.loads(row[0])
    for schedule in result["schedules"]:
        observed = schedule.get("observer_as_of")
        if (
            observed
            and not 0
            <= (now - datetime.fromisoformat(observed)).total_seconds()
            <= schedule["observer_max_age_seconds"]
        ):
            schedule.update(next_due_at=None, reason="observer_stale")
        due = schedule.get("next_due_at")
        if due and now > datetime.fromisoformat(due) + timedelta(seconds=schedule["grace_seconds"]):
            schedule.update(next_due_at=None, reason="grace_elapsed_unreconciled")
    for run in (result.get("latest_run"), result.get("active_run")):
        if run and run["status"] == "running":
            expiry = run.get("lease_expires_at")
            if not expiry or datetime.fromisoformat(expiry) <= now:
                run["status"] = "stale"
                run["reason"] = "heartbeat_expired_unreconciled"
    return result


def history(
    conn: sqlite3.Connection, scope: str, *, limit: int = 25, cursor: str | None = None
) -> dict[str, Any]:
    import base64

    from app.public.queries import Cursor, RestartRequired

    if not 1 <= limit <= 100:
        raise ValueError("invalid_limit")
    if not table_exists(conn, "public_activity"):
        return {"items": [], "next_cursor": None, "total": 0}
    revision = conn.execute("SELECT revision FROM activity_meta WHERE singleton=1").fetchone()[0]
    after = (
        Cursor.model_validate_json(base64.urlsafe_b64decode(cursor.encode()).decode())
        if cursor
        else None
    )
    if after and after.query != scope:
        raise ValueError("cursor_query_mismatch")
    if after and after.revision != revision:
        raise RestartRequired("activity_changed")
    high_water = (
        after.high_water
        if after
        else conn.execute("SELECT COALESCE(MAX(sequence), 0) FROM public_activity").fetchone()[0]
    )
    params: list[Any] = [scope, high_water]
    where = "portfolio_id=? AND sequence<=?"
    total = conn.execute("SELECT COUNT(*) FROM public_activity WHERE " + where, params).fetchone()[
        0
    ]
    if after:
        where += " AND (created_at, public_id)<(?, ?)"
        params.extend([after.created_at, after.public_id])
    rows = conn.execute(
        "SELECT created_at, public_id, feed_content FROM public_activity WHERE "
        + where
        + " ORDER BY created_at DESC, public_id DESC LIMIT ?",
        [*params, limit + 1],
    ).fetchall()
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = base64.urlsafe_b64encode(
            Cursor(
                revision=revision,
                high_water=high_water,
                query=scope,
                created_at=last[0],
                public_id=last[1],
            )
            .model_dump_json()
            .encode()
        ).decode()
    return {
        "items": [json.loads(row[2]) for row in rows[:limit]],
        "next_cursor": next_cursor,
        "total": total,
        "activity_revision": revision,
    }
