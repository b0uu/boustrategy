"""Trusted source-side change counters for resumable public publication."""

import sqlite3
from uuid import uuid4

_TABLE_SECTIONS = {
    "decision_records": ("details",),
    "order_intents": ("details", "performance"),
    "status_events": ("details",),
    "policy_evaluations": ("details",),
    "live_execution_packets": ("details",),
    "broker_execution_records": ("details",),
    "broker_execution_events": ("details",),
    "public_source_records": ("details", "performance"),
    "thesis_reviews": ("performance",),
    "reporting_observations": ("details", "performance"),
    "live_portfolio_snapshots": ("details", "performance"),
    "paper_fills": ("details", "performance"),
    "paper_positions": ("performance",),
    "daily_prices": ("performance",),
    "regime_snapshots": ("details", "performance"),
    "reasoning_runs": ("details", "activity"),
    "reasoning_run_decisions": ("details", "activity"),
    "runtime_runs": ("activity",),
    "runtime_attempts": ("activity",),
    "schedule_revisions": ("activity",),
    "scheduler_observations": ("activity",),
    "schedule_occurrences": ("activity",),
}


def initialize_changes(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS publication_changes "
        "(singleton INTEGER PRIMARY KEY CHECK(singleton=1), source_id TEXT NOT NULL, "
        "details INTEGER NOT NULL, performance INTEGER NOT NULL, activity INTEGER NOT NULL)"
    )
    conn.execute("INSERT OR IGNORE INTO publication_changes VALUES (1, ?, 0, 0, 0)", (uuid4().hex,))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS publication_activity_changes (kind "
        "TEXT NOT NULL, source_id TEXT NOT NULL, revision INTEGER NOT "
        "NULL, PRIMARY KEY(kind, source_id))"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS activity_changes_revision ON "
        "publication_activity_changes (kind, revision)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS publication_decision_changes "
        "(decision_id TEXT PRIMARY KEY, revision INTEGER NOT NULL)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS decision_changes_revision ON "
        "publication_decision_changes (revision)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS publication_rebuild (singleton INTEGER "
        "PRIMARY KEY, details_revision INTEGER NOT NULL)"
    )
    conn.execute("INSERT OR IGNORE INTO publication_rebuild VALUES (1, 0)")
    identities = {
        "runtime_runs": ("runtime", "run_id"),
        "runtime_attempts": ("runtime", "run_id"),
        "reasoning_runs": ("legacy", "reasoning_run_id"),
        "schedule_occurrences": ("occurrence", "occurrence_id"),
    }
    for table, sections in _TABLE_SECTIONS.items():
        assignments = ", ".join(f"{section}={section}+1" for section in sections)
        for event in ("INSERT", "UPDATE", "DELETE"):
            dirty = ""
            if table in identities:
                kind, field = identities[table]
                row = "old" if event == "DELETE" else "new"
                dirty = (
                    f"INSERT INTO publication_activity_changes VALUES ('{kind}', {row}.{field}, "
                    "(SELECT activity FROM publication_changes WHERE singleton=1)) "
                    "ON CONFLICT(kind, source_id) DO UPDATE SET revision=excluded.revision;"
                )
            if "details" in sections:
                row = "old" if event == "DELETE" else "new"
                selected = None
                if table in {
                    "decision_records",
                    "policy_evaluations",
                    "order_intents",
                    "reasoning_run_decisions",
                }:
                    selected = f"SELECT {row}.decision_id AS decision_id"
                elif table in {
                    "live_execution_packets",
                    "broker_execution_records",
                    "broker_execution_events",
                    "paper_fills",
                }:
                    selected = (
                        "SELECT decision_id FROM order_intents "
                        f"WHERE order_intent_id={row}.order_intent_id"
                    )
                elif table == "status_events":
                    selected = (
                        f"SELECT {row}.subject_id AS decision_id "
                        f"WHERE {row}.subject_type='decision' "
                        "UNION SELECT decision_id FROM order_intents "
                        f"WHERE order_intent_id={row}.subject_id"
                    )
                elif table == "reasoning_runs":
                    selected = (
                        "SELECT decision_id FROM reasoning_run_decisions "
                        f"WHERE reasoning_run_id={row}.reasoning_run_id"
                    )
                if selected is None:
                    dirty += (
                        "UPDATE publication_rebuild SET details_revision=(SELECT details "
                        "FROM publication_changes WHERE singleton=1) WHERE singleton=1;"
                    )
                else:
                    dirty += (
                        "INSERT INTO publication_decision_changes SELECT decision_id, "
                        "(SELECT details FROM publication_changes WHERE singleton=1) FROM ("
                        + selected
                        + ") WHERE 1 ON CONFLICT(decision_id) DO UPDATE SET "
                        "revision=excluded.revision;"
                    )
            conn.execute(
                f"CREATE TRIGGER IF NOT EXISTS publish_{table}_{event.lower()} AFTER {event} "
                f"ON {table} BEGIN UPDATE publication_changes SET {assignments} "
                f"WHERE singleton=1; {dirty} END"
            )
