# Plan 006: Persist decision records and order intents with idempotent writes (SQLite)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat e869d55..HEAD -- app/ tests/ .gitignore`
> Compare the "Current state" excerpts below against the live code before
> proceeding; on a mismatch, STOP. Assumes **plans 001-003 and 005 have
> landed** (stable record schema; `OrderIntent` exists).

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW (new module; nothing existing depends on it yet)
- **Depends on**: plans/005 (OrderIntent schema)
- **Category**: direction
- **Planned at**: commit `e869d55`, 2026-07-10

## Why this matters

Records currently exist only in memory during tests. The spec requires
(§13): "After a crash, resume from the last safe state rather than creating
duplicate orders." That property is built here, before any broker code
exists, because idempotent storage is much cheaper to build under the
pipeline than to retrofit around it. The rule this plan implements: writing
the same record twice is a harmless no-op; writing a *different* record
under an existing ID is an integrity violation that crashes loudly. Those
two behaviors are what make crash-resume safe.

Technology decision (made deliberately, executor should not revisit):
SQLite via the Python standard library `sqlite3`. Zero dependencies, zero
cost (fits the spec's $0-25 storage budget), single file, real uniqueness
constraints. Full records are stored as JSON in the row alongside a few
extracted, indexed columns for querying.

## Current state

- `app/schemas/decision_record.py` — `InvestmentDecisionRecord`, a pydantic
  model. Serialization round-trip is `record.model_dump_json()` /
  `InvestmentDecisionRecord.model_validate_json(...)`.
- `app/schemas/order_intent.py` (from plan 005) — `OrderIntent`, same
  round-trip pattern.
- `tests/fixtures/decision_records.py` — `valid_decision_record()`,
  `decision_record_with(**overrides)`.
- No `app/storage/` package and no `data/` directory exist.
- `.gitignore` currently ignores: `__pycache__/`, `*.py[cod]`,
  `.pytest_cache/`, `*.egg-info/`, `.venv/`, `venv/`, `scratchpad/`.

Repo conventions: crash early; no premature abstractions (no ORM, no
repository-pattern class hierarchy — plain functions taking a connection);
"why" comments only; tests mirror `app/` layout, plain pytest functions.

## Commands you will need

| Purpose | Command                           | Expected on success |
|---------|-----------------------------------|---------------------|
| Install | `python -m pip install -e .[dev]` | exit 0              |
| Tests   | `python -m pytest -q`             | all pass, exit 0    |
| Lint*   | `python -m ruff check .`          | exit 0              |
| Types*  | `python -m mypy app tests`        | exit 0              |

*Only if plan 004 has landed.

## Scope

**In scope** (create/modify only these):

- `app/storage/__init__.py` (create, empty)
- `app/storage/database.py` (create)
- `app/storage/records.py` (create)
- `tests/storage/__init__.py` (create, empty)
- `tests/storage/test_records.py` (create)
- `.gitignore` (one line added: `data/`)

**Out of scope** (do NOT touch):

- Schema and policy modules — read-only inputs.
- Any state-machine/status-transition logic; any broker code.
- Price data storage (plan 007 adds its own table via the same helper).
- No new dependencies: stdlib `sqlite3` only.

## Git workflow

- Branch: `advisor/006-record-persistence`
- Commit style: short lowercase imperative summary, matching existing history.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Database helper

Create `app/storage/database.py`:

```python
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
    intent_json TEXT NOT NULL
);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    return conn
```

The `decision_id UNIQUE` constraint on `order_intents` is the database-level
enforcement of "one decision, one intent" (matching plan 005's deterministic
`oi_<decision_id>` derivation).

**Verify**: `python -c "from app.storage.database import connect; c = connect(':memory:'); print([r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")])"` → prints both table names.

### Step 2: Idempotent save/load functions

Create `app/storage/records.py` with four plain functions:

```python
def save_decision_record(conn, record: InvestmentDecisionRecord) -> bool: ...
def get_decision_record(conn, decision_id: str) -> InvestmentDecisionRecord | None: ...
def save_order_intent(conn, intent: OrderIntent) -> bool: ...
def get_order_intent(conn, order_intent_id: str) -> OrderIntent | None: ...
```

Save semantics (identical for both types) — this is the core of the plan:

1. Serialize with `model_dump_json()`.
2. If no row exists for the ID: insert, commit, return `True`.
3. If a row exists and its stored JSON equals the new JSON: **no-op, return
   `False`** (idempotent replay — the crash-resume case).
4. If a row exists with different JSON: **raise `ValueError`** naming the ID
   (an ID collision with different content is corruption or a logic bug;
   crash early, never overwrite an audit record).

Records are append-only by design: there is no update or delete function.
An audit trail that can be edited is not an audit trail.

Load semantics: fetch by primary key, `model_validate_json` the stored JSON,
return `None` when absent.

**Verify**: `python -m pytest -q` → existing tests still pass.

### Step 3: Ignore the data directory

Add `data/` on its own line to `.gitignore` (the runtime database will live
at `data/boustrategy.db` by caller convention; the database is runtime
state, not source).

**Verify**: `git check-ignore data/boustrategy.db` → prints the path, exit 0.

### Step 4: Tests

Create `tests/storage/test_records.py` per the Test plan.

**Verify**: `python -m pytest tests/storage -q` → all pass.

## Test plan

In `tests/storage/test_records.py`, each test opening `connect(":memory:")`
(or `tmp_path / "test.db"` where file behavior matters):

1. `test_decision_record_round_trip` — save fixture record, load by id,
   loaded model equals the original (`==` on pydantic models).
2. `test_saving_identical_record_twice_is_noop` — first save returns True,
   second returns False, exactly one row exists.
3. `test_saving_conflicting_record_raises` — save fixture, then save a
   record with the same `decision_id` but a different field (use
   `decision_record_with(internal_notes="changed")`) →
   `pytest.raises(ValueError)`.
4. `test_get_missing_record_returns_none`.
5. `test_order_intent_round_trip` — build an intent via
   `create_order_intent(valid_decision_record(), PolicyResult(approved=True))`,
   save, load, equal.
6. `test_second_intent_for_same_decision_is_rejected` — two *different*
   intents sharing a `decision_id` (construct the second manually with a
   different `order_intent_id`) → save of the second raises (the UNIQUE
   constraint; catch `sqlite3.IntegrityError` and re-raise as `ValueError`
  in the save function so callers see one exception type).
7. `test_database_file_created_on_connect` — `connect(tmp_path / "sub" / "x.db")`
   creates parent directories and the file exists after a write.

Verification: `python -m pytest -q` → all pass, 7 new tests included.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `python -m pytest -q` exits 0; 7 new tests in `tests/storage/`
- [ ] `grep -n "^data/$" .gitignore` → one match
- [ ] `python -c "import app.storage.records as r; import inspect; assert not any(n.startswith(('update_', 'delete_')) for n, _ in inspect.getmembers(r))"` exits 0 (append-only surface)
- [ ] No new entries under `[project.dependencies]` in `pyproject.toml` (stdlib only)
- [ ] If plan 004 landed: `python -m ruff check .` and `python -m mypy app tests` exit 0
- [ ] `git status --porcelain` shows only the six in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `app/schemas/order_intent.py` does not exist (plan 005 has not landed).
- Pydantic JSON round-trip is not stable for any field (loaded model !=
  original) — report the field rather than patching serialization ad hoc.
- You find yourself wanting an update/delete function to make something
  work — append-only is a design decision; a use case that breaks it needs
  the maintainer.

## Maintenance notes

- Plan 007 (price cache) adds its own table through
  `app/storage/database.py`'s `_SCHEMA`; keep table DDL centralized there.
- Linking `record.order_intent_id` (currently always None on stored
  records) is state-machine work: the future transition that creates an
  intent should persist the intent AND a status event, not mutate the
  stored decision record (append-only).
- When the dashboard needs queries beyond get-by-id (list by date, by
  ticker, by decision), add read-only query functions here; the extracted
  columns (`created_at`, `ticker`, `decision`, `side`) exist for exactly
  that.
