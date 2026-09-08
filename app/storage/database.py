import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runtime_runs (
    run_id TEXT PRIMARY KEY, public_id TEXT NOT NULL UNIQUE, scope_key TEXT NOT NULL,
    mode TEXT NOT NULL, account_id TEXT NOT NULL, execution_profile_id TEXT NOT NULL,
    session_date TEXT NOT NULL, slot TEXT NOT NULL, prepared_at TEXT NOT NULL,
    reasoning_run_id TEXT, occurrence_id TEXT UNIQUE, run_json TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS runtime_legacy_identity ON runtime_runs(reasoning_run_id)
    WHERE reasoning_run_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS runtime_attempts (
    attempt_id TEXT PRIMARY KEY, public_id TEXT NOT NULL UNIQUE,
    run_id TEXT NOT NULL REFERENCES runtime_runs(run_id),
    attempt_number INTEGER NOT NULL, fence INTEGER NOT NULL, status TEXT NOT NULL,
    stage TEXT NOT NULL, model TEXT NOT NULL, observed_model TEXT, started_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL, finished_at TEXT, reason TEXT, public_summary TEXT,
    UNIQUE(run_id, attempt_number)
);
CREATE TABLE IF NOT EXISTS runtime_leases (
    scope_key TEXT PRIMARY KEY, fence INTEGER NOT NULL, attempt_id TEXT, expires_at TEXT
);
CREATE TABLE IF NOT EXISTS schedule_revisions (
    schedule_id TEXT NOT NULL, revision INTEGER NOT NULL, scope_key TEXT NOT NULL,
    record_json TEXT NOT NULL, PRIMARY KEY(schedule_id, revision)
);
CREATE TABLE IF NOT EXISTS scheduler_observations (
    schedule_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, observed_at TEXT NOT NULL,
    record_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS schedule_occurrences (
    occurrence_id TEXT PRIMARY KEY, public_id TEXT NOT NULL UNIQUE, schedule_id TEXT NOT NULL,
    revision INTEGER NOT NULL, session_date TEXT NOT NULL, due_at TEXT NOT NULL,
    status TEXT NOT NULL, reason TEXT, observed_at TEXT NOT NULL,
    UNIQUE(schedule_id, session_date)
);

CREATE TABLE IF NOT EXISTS public_source_records (
    revision_id TEXT PRIMARY KEY, source_ref TEXT NOT NULL, public_id TEXT NOT NULL,
    supersedes TEXT UNIQUE REFERENCES public_source_records(revision_id),
    record_json TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS source_root ON public_source_records(source_ref)
    WHERE supersedes IS NULL;
CREATE TABLE IF NOT EXISTS thesis_reviews (
    review_id TEXT PRIMARY KEY, mode TEXT NOT NULL, account_id TEXT NOT NULL,
    episode_id TEXT NOT NULL, reviewed_at TEXT NOT NULL, record_json TEXT NOT NULL,
    UNIQUE(mode, account_id, episode_id, reviewed_at)
);

CREATE TABLE IF NOT EXISTS policy_evaluations (
    decision_id TEXT PRIMARY KEY REFERENCES decision_records(decision_id),
    evaluated_at TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    evaluation_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reporting_observations (
    observation_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    account_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    external_event_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    supersedes TEXT UNIQUE REFERENCES reporting_observations(observation_id),
    voided INTEGER NOT NULL,
    observation_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS reporting_account_time ON reporting_observations
    (mode, account_id, occurred_at, observation_id);
CREATE UNIQUE INDEX IF NOT EXISTS reporting_external_event ON reporting_observations
    (mode, account_id, kind, external_event_id) WHERE supersedes IS NULL;

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
    execution_profile_id TEXT NOT NULL DEFAULT '',
    intent_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS live_execution_packets (
    execution_packet_id TEXT PRIMARY KEY,
    order_intent_id TEXT NOT NULL,
    execution_profile_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    notional REAL NOT NULL,
    limit_price REAL NOT NULL,
    packet_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS broker_execution_records (
    broker_execution_record_id TEXT PRIMARY KEY,
    order_intent_id TEXT NOT NULL UNIQUE,
    execution_packet_id TEXT NOT NULL,
    execution_profile_id TEXT NOT NULL,
    account_alias TEXT NOT NULL,
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
    execution_packet_id TEXT NOT NULL,
    execution_profile_id TEXT NOT NULL,
    status TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    event_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS live_portfolio_snapshots (
    portfolio_snapshot_id TEXT PRIMARY KEY,
    execution_profile_id TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    account_equity REAL NOT NULL,
    snapshot_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reasoning_runs (
    reasoning_run_id TEXT PRIMARY KEY,
    session_date TEXT NOT NULL,
    slot TEXT NOT NULL,
    execution_profile_id TEXT NOT NULL,
    model_label TEXT NOT NULL,
    shared_bundle_sha256 TEXT NOT NULL,
    portfolio_snapshot_id TEXT NOT NULL,
    result TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    run_json TEXT NOT NULL,
    UNIQUE(session_date, slot, execution_profile_id)
);
CREATE TABLE IF NOT EXISTS reasoning_run_decisions (
    reasoning_run_id TEXT NOT NULL,
    decision_id TEXT NOT NULL UNIQUE,
    submission_snapshot_id TEXT NOT NULL,
    PRIMARY KEY (reasoning_run_id, decision_id)
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
CREATE TABLE IF NOT EXISTS x_fetch_checkpoints (
    handle TEXT PRIMARY KEY,
    since_id TEXT,
    start_time TEXT,
    next_token TEXT
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


def connect(db_path: str | Path, *, wal: bool = False) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        if wal:
            conn.execute("PRAGMA journal_mode = WAL")
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
            {
                "execution_mode": "TEXT NOT NULL DEFAULT 'PAPER'",
                "execution_profile_id": "TEXT NOT NULL DEFAULT ''",
            },
        )
        _ensure_columns(
            conn,
            "broker_execution_records",
            {
                "execution_packet_id": "TEXT NOT NULL DEFAULT ''",
                "execution_profile_id": "TEXT NOT NULL DEFAULT ''",
                "account_alias": "TEXT NOT NULL DEFAULT ''",
            },
        )
        _ensure_columns(
            conn,
            "broker_execution_events",
            {
                "execution_packet_id": "TEXT NOT NULL DEFAULT ''",
                "execution_profile_id": "TEXT NOT NULL DEFAULT ''",
            },
        )
        _ensure_columns(
            conn,
            "reasoning_run_decisions",
            {"submission_snapshot_id": "TEXT NOT NULL DEFAULT ''"},
        )
        _ensure_columns(
            conn, "paper_fills", {"simulation_version": "TEXT NOT NULL DEFAULT 'legacy_close_v1'"}
        )
        _ensure_columns(
            conn, "decision_records", {"runtime_attempt_id": "TEXT NOT NULL DEFAULT ''"}
        )
        from app.storage.publication_changes import initialize_changes

        initialize_changes(conn)
        conn.commit()
    except BaseException:
        conn.close()
        raise
    return conn
