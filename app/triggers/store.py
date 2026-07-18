import json
import sqlite3
from datetime import date


def trigger_id(trigger_type: str, subject: str, event_date: date) -> str:
    return f"{trigger_type}:{subject}:{event_date.isoformat()}"


def insert_trigger(
    conn: sqlite3.Connection,
    trigger_type: str,
    subject: str,
    event_date: date,
    fired_at: date,
    details: dict[str, object],
) -> bool:
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO trigger_events
            (trigger_id, trigger_type, subject, fired_at, details_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            trigger_id(trigger_type, subject, event_date),
            trigger_type,
            subject,
            fired_at.isoformat(),
            json.dumps(details, sort_keys=True),
        ),
    )
    conn.commit()
    return cursor.rowcount == 1


def mark_triggers(conn: sqlite3.Connection, ids: list[str], status: str) -> int:
    if status not in ("consumed", "expired"):
        raise ValueError(f"invalid target trigger status {status!r}")
    for item in ids:
        row = conn.execute(
            "SELECT status FROM trigger_events WHERE trigger_id = ?", (item,)
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown trigger_id {item!r}")
        if row[0] != "pending":
            raise ValueError(f"trigger {item!r} cannot transition from {row[0]} to {status}")
    conn.executemany(
        "UPDATE trigger_events SET status = ? WHERE trigger_id = ?",
        [(status, item) for item in ids],
    )
    conn.commit()
    return len(ids)


def expire_triggers(conn: sqlite3.Connection, before: date) -> int:
    cursor = conn.execute(
        """
        UPDATE trigger_events SET status = 'expired'
        WHERE status = 'pending' AND fired_at < ?
        """,
        (before.isoformat(),),
    )
    conn.commit()
    return cursor.rowcount
