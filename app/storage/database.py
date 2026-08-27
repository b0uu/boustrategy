import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS decision_records (
    decision_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    ticker TEXT NOT NULL,
    decision TEXT NOT NULL,
    record_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS order_intents (
    order_intent_id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    execution_mode TEXT NOT NULL DEFAULT 'PAPER',
    intent_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS broker_execution_records (
    broker_execution_record_id TEXT PRIMARY KEY,
    order_intent_id TEXT NOT NULL UNIQUE,
    submitted_at TEXT NOT NULL,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    status TEXT NOT NULL,
    broker_order_id TEXT NOT NULL UNIQUE,
    record_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS broker_execution_events (
    broker_event_id TEXT PRIMARY KEY,
    broker_execution_record_id TEXT NOT NULL,
    order_intent_id TEXT NOT NULL,
    status TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    event_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS daily_prices (
    ticker TEXT NOT NULL,
    bar_date TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    adj_close REAL,
    volume INTEGER NOT NULL,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (ticker, bar_date)
);
CREATE TABLE IF NOT EXISTS status_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    status TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS x_accounts (
    handle TEXT PRIMARY KEY,
    user_id TEXT,
    categories TEXT NOT NULL DEFAULT '[]',
    included_reason TEXT NOT NULL DEFAULT '',
    tier TEXT NOT NULL DEFAULT 'core',
    status TEXT NOT NULL DEFAULT 'active'
);
CREATE TABLE IF NOT EXISTS x_account_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    handle TEXT NOT NULL,
    change TEXT NOT NULL,
    occurred_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS x_posts (
    post_id TEXT PRIMARY KEY,
    handle TEXT NOT NULL,
    posted_at TEXT NOT NULL,
    text TEXT NOT NULL,
    url TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'unreviewed',
    conversation_id TEXT NOT NULL DEFAULT '',
    reply_context TEXT NOT NULL DEFAULT '',
    media_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS x_post_reads (
    month TEXT PRIMARY KEY,
    post_reads INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS x_signals (
    entry_id TEXT PRIMARY KEY,
    post_id TEXT NOT NULL,
    handle TEXT NOT NULL,
    signal_json TEXT NOT NULL,
    captured_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS x_gate_predictions (
    post_id TEXT NOT NULL,
    predictor TEXT NOT NULL,
    prediction TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    predicted_at TEXT NOT NULL,
    PRIMARY KEY (post_id, predictor)
);
CREATE TABLE IF NOT EXISTS x_adjudications (
    post_id TEXT NOT NULL,
    predictor TEXT NOT NULL,
    verdict TEXT NOT NULL,
    label_before TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    adjudicated_at TEXT NOT NULL,
    PRIMARY KEY (post_id, predictor)
);
CREATE TABLE IF NOT EXISTS x_score_snapshots (
    predictor TEXT NOT NULL,
    label TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (predictor, label)
);
CREATE TABLE IF NOT EXISTS x_runs (
    run_id TEXT PRIMARY KEY,
    slot TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    posts_fetched INTEGER NOT NULL DEFAULT 0,
    posts_exported INTEGER NOT NULL DEFAULT 0,
    reads_used INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'started'
);
CREATE TABLE IF NOT EXISTS x_route_decisions (
    post_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    route TEXT NOT NULL,
    rank TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    predictor TEXT NOT NULL,
    decided_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS x_article_queue (
    post_id TEXT PRIMARY KEY,
    queued_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    resolution TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS x_digest_notes (
    note_date TEXT NOT NULL,
    slot TEXT NOT NULL,
    synthesis TEXT NOT NULL,
    author TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (note_date, slot)
);
CREATE TABLE IF NOT EXISTS calendar_events (
    event_type TEXT NOT NULL,
    ticker TEXT NOT NULL DEFAULT '',
    event_date TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (event_type, ticker, event_date)
);
CREATE TABLE IF NOT EXISTS trigger_events (
    trigger_id TEXT PRIMARY KEY,
    trigger_type TEXT NOT NULL,
    subject TEXT NOT NULL,
    fired_at TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending'
);
CREATE TABLE IF NOT EXISTS regime_snapshots (
    snapshot_date TEXT PRIMARY KEY,
    regime TEXT NOT NULL,
    raw_regime TEXT NOT NULL,
    score INTEGER NOT NULL,
    components_json TEXT NOT NULL,
    computed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_fills (
    fill_id TEXT PRIMARY KEY,
    order_intent_id TEXT NOT NULL UNIQUE,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    shares REAL NOT NULL,
    price REAL NOT NULL,
    fill_date TEXT NOT NULL,
    filled_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_positions (
    ticker TEXT PRIMARY KEY,
    shares REAL NOT NULL,
    avg_cost REAL NOT NULL,
    opened_at TEXT NOT NULL,
    primary_theme_id TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS newsletter_docs (
    doc_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    received_at TEXT NOT NULL,
    archive_path TEXT NOT NULL,
    parse_status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS newsletter_claims (
    claim_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    claim TEXT NOT NULL,
    claim_type TEXT NOT NULL,
    stance TEXT NOT NULL,
    horizon TEXT NOT NULL,
    tickers TEXT NOT NULL DEFAULT '[]',
    primary_theme_id TEXT NOT NULL DEFAULT '',
    why_it_matters TEXT NOT NULL DEFAULT '',
    annotated_by TEXT NOT NULL,
    annotated_at TEXT NOT NULL
);
"""


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    for name, ddl in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def connect(db_path: str | Path) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    # Live trial database predates these columns; additive ALTER TABLE keeps
    # existing rows intact (they get empty-string context, which is correct —
    # we never backfill context for posts fetched before this migration).
    _ensure_columns(
        conn,
        "x_posts",
        {
            "conversation_id": "TEXT NOT NULL DEFAULT ''",
            "reply_context": "TEXT NOT NULL DEFAULT ''",
            "media_json": "TEXT NOT NULL DEFAULT '[]'",
        },
    )
    _ensure_columns(
        conn,
        "order_intents",
        {"execution_mode": "TEXT NOT NULL DEFAULT 'PAPER'"},
    )
    conn.commit()
    return conn
