# Plan 009: Backend state machine — decision pipeline with status log and crash-safe resume

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> a STOP condition occurs, stop and report — do not improvise. When done,
> update this plan's status row in `plans/README.md` — unless a reviewer
> dispatched you and told you they maintain the index.
>
> **Drift check (run first)**: `git diff --stat e8c5dbe..HEAD -- app/ tests/`
> Compare "Current state" excerpts against live code; on mismatch, STOP.
> Requires plans 001-007 landed (all DONE and verified on main).

## Status

- **Priority**: P1
- **Effort**: M
- **Depends on**: 005, 006 (order intents + storage)
- **Category**: direction
- **Planned at**: commit `e8c5dbe`, 2026-07-12

## Why this matters

The pipeline pieces exist but nothing connects them: schema validation,
policy evaluation, intent creation, and storage are separate functions with
no orchestrator, no recorded lifecycle, and no crash story. The spec (§13)
requires decision statuses (`decision_record_created`, `schema_validated`,
`schema_failed`, `policy_approved`, `policy_rejected`,
`order_intent_created`, ...) and crash-safe resume: "After a crash, resume
from the last safe state rather than creating duplicate orders." This plan
builds `process_decision` — the single entrypoint that runs raw decision
data through the whole gauntlet, appending an auditable status event at
each step, idempotently: re-running the same decision after a crash
produces no duplicate records, no duplicate intents, no duplicate statuses.

Deliberately deferred: broker-side statuses (`submitted`, `filled`, ... —
broker adapter phase), trigger/source-pack statuses (those objects don't
exist yet), and any scheduling.

## Current state

- `app/schemas/decision_record.py` — `InvestmentDecisionRecord`;
  `model_validate` raises `pydantic.ValidationError` on bad data.
- `app/policy/decision_policy.py` — `evaluate_decision_policy(record,
  portfolio: PortfolioContext | None = None) -> PolicyResult` where
  `PolicyResult` has `approved: bool`, `reasons: list[str]`.
- `app/orders/create_order_intent.py` — `create_order_intent(record,
  policy_result, created_at=None) -> OrderIntent`; raises `ValueError` on
  unapproved or non-actionable records; deterministic id `oi_<decision_id>`.
- `app/storage/database.py` — `connect(db_path)` with `_SCHEMA`
  executescript; all table DDL centralized here.
- `app/storage/records.py` — `save_decision_record` / `save_order_intent`
  (idempotent: identical re-save returns False; conflicting content raises
  ValueError), `get_decision_record` / `get_order_intent`.
- No `app/state/` package exists.
- Gates (plan 004 landed): `python -m ruff check .`,
  `python -m ruff format --check .`, `python -m mypy app tests` must all
  exit 0. `AGENTS.md` documents conventions.

Conventions: `StrEnum` enums; pydantic models with
`ConfigDict(extra="forbid")`; crash early (raise, never silently skip);
plain functions taking a `sqlite3.Connection`; append-only stores; tests
mirror `app/` under `tests/`, arrange/act/assert.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Install | `python -m pip install -e .[dev]` | exit 0 |
| Tests | `python -m pytest -q` | all pass |
| Lint | `python -m ruff check .` && `python -m ruff format --check .` | exit 0 |
| Types | `python -m mypy app tests` | exit 0 |

## Scope

**In scope** (create/modify only these):

- `app/state/__init__.py` (create, empty)
- `app/state/pipeline.py` (create)
- `app/storage/database.py` (extend `_SCHEMA` with `status_events` only)
- `tests/state/__init__.py` (create, empty)
- `tests/state/test_pipeline.py` (create)

**Out of scope**: broker statuses/transitions; schema or policy changes;
triggers; scheduling; everything under `app/x/` (plan 010); mutation of
stored decision records (append-only — the status log records lifecycle,
the record itself is never edited).

## Git workflow

- Branch: `advisor/009-backend-state-machine`
- Short lowercase imperative commit messages. Do NOT push.

## Steps

### Step 1: status_events table

Append to `_SCHEMA` in `app/storage/database.py`:

```sql
CREATE TABLE IF NOT EXISTS status_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    status TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
```

**Verify**: `python -c "from app.storage.database import connect; connect(':memory:').execute('SELECT * FROM status_events')"` → exit 0.

### Step 2: statuses, transitions, and the append function

Create `app/state/pipeline.py` with:

```python
class DecisionStatus(StrEnum):
    DECISION_RECORD_CREATED = "decision_record_created"
    SCHEMA_VALIDATED = "schema_validated"
    SCHEMA_FAILED = "schema_failed"
    POLICY_APPROVED = "policy_approved"
    POLICY_REJECTED = "policy_rejected"
    ORDER_INTENT_CREATED = "order_intent_created"


_LEGAL_TRANSITIONS: dict[DecisionStatus | None, set[DecisionStatus]] = {
    None: {DecisionStatus.DECISION_RECORD_CREATED, DecisionStatus.SCHEMA_FAILED},
    DecisionStatus.DECISION_RECORD_CREATED: {DecisionStatus.SCHEMA_VALIDATED},
    DecisionStatus.SCHEMA_VALIDATED: {
        DecisionStatus.POLICY_APPROVED,
        DecisionStatus.POLICY_REJECTED,
    },
    DecisionStatus.POLICY_APPROVED: {DecisionStatus.ORDER_INTENT_CREATED},
    DecisionStatus.POLICY_REJECTED: set(),
    DecisionStatus.SCHEMA_FAILED: set(),
    DecisionStatus.ORDER_INTENT_CREATED: set(),
}
```

Functions:

- `latest_status(conn, subject_id: str) -> DecisionStatus | None` — most
  recent `status_events` row for `subject_type="decision"`.
- `append_status(conn, subject_id: str, status: DecisionStatus, detail: str = "") -> bool` —
  idempotent resume semantics: if the latest status already equals
  `status`, no-op and return False; if `status` is not in
  `_LEGAL_TRANSITIONS[latest]`, and `status` is not an *earlier* stage
  already present in the subject's history (re-run replay), raise
  `ValueError`; otherwise insert (occurred_at = now(UTC) isoformat) and
  return True. "Already present in history" check: a re-run of
  `process_decision` re-encounters earlier statuses — those are skipped
  silently (return False), not errors.

**Verify**: `python -m pytest -q` → existing tests still pass.

### Step 3: process_decision

In the same module:

```python
class ProcessOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str | None
    final_status: DecisionStatus
    policy_reasons: list[str] = Field(default_factory=list)
    order_intent_id: str | None = None


def process_decision(
    conn: sqlite3.Connection,
    record_data: dict[str, Any],
    portfolio: PortfolioContext | None = None,
) -> ProcessOutcome: ...
```

Flow, in order:

1. `InvestmentDecisionRecord.model_validate(record_data)`. On
   `ValidationError`: if `record_data.get("decision_id")` is a non-empty
   string, `append_status(..., SCHEMA_FAILED, detail=str(error)[:500])`;
   return `ProcessOutcome(decision_id=<id or None>,
   final_status=SCHEMA_FAILED)`. Never raise for invalid input — rejection
   is an outcome, not a crash (the caller is eventually an LLM-facing API).
2. `save_decision_record(conn, record)` (idempotent; a content conflict
   still raises — that IS a crash-worthy integrity violation).
3. `append_status(DECISION_RECORD_CREATED)`, `append_status(SCHEMA_VALIDATED)`.
4. `evaluate_decision_policy(record, portfolio)` →
   `append_status(POLICY_APPROVED)` or `append_status(POLICY_REJECTED,
   detail=", ".join(reasons))`; rejected → return outcome.
5. If approved and the decision is actionable (BUY/ADD/TRIM/SELL): check
   `get_order_intent(conn, f"oi_{record.decision_id}")` first — if it
   already exists (crash re-run), reuse it; otherwise
   `create_order_intent(record, result)` and `save_order_intent`. Then
   `append_status(ORDER_INTENT_CREATED)`. The check-before-create is
   load-bearing: `create_order_intent` stamps `created_at=now()`, so
   re-creating after a crash would produce different JSON and trip the
   storage conflict guard. Return outcome with the intent id.
6. Approved but non-actionable (HOLD/PASS/WATCHLIST): final status stays
   POLICY_APPROVED, `order_intent_id=None`.

**Verify**: `python -m pytest -q` → all pass.

### Step 4: tests

Create `tests/state/test_pipeline.py` per Test plan.

**Verify**: `python -m pytest -q`, `python -m ruff check .`,
`python -m ruff format --check .`, `python -m mypy app tests` → all exit 0.

## Test plan

Using `connect(":memory:")` and `valid_decision_record_data()` /
`decision_record_with` from fixtures:

1. `test_approved_buy_runs_full_chain` — outcome ORDER_INTENT_CREATED,
   intent id `oi_dec_001`, statuses in order: created → validated →
   approved → intent_created; record and intent retrievable from storage.
2. `test_schema_failure_is_an_outcome_not_a_crash` — `ticker="   "` →
   SCHEMA_FAILED outcome, a `schema_failed` status row exists with detail,
   no record stored.
3. `test_policy_rejection_stops_the_chain` — `regime_state="RED"` BUY →
   POLICY_REJECTED with reasons; no intent exists; record IS stored
   (rejected decisions are audit records too).
4. `test_non_actionable_approved_creates_no_intent` — decision="HOLD"
   (weights within caps) → POLICY_APPROVED, `order_intent_id is None`.
5. `test_rerun_is_idempotent` — call `process_decision` twice with
   identical data: same outcome both times, exactly one record, one
   intent, and no duplicated status rows (count status_events).
6. `test_illegal_transition_raises` — `append_status` directly:
   POLICY_APPROVED on a fresh subject (no prior statuses) raises ValueError.
7. `test_portfolio_context_flows_through` — BUY with
   `PortfolioContext(holdings_count=10, buy_add_trades_today=0,
   sell_trim_trades_today=0)` → POLICY_REJECTED with
   `max_holdings_reached` in reasons.

## Done criteria

- [ ] `python -m pytest -q` exits 0; 7 new tests in `tests/state/`
- [ ] All four plan-004 gates exit 0
- [ ] `python -c "from app.storage.database import connect; from app.state.pipeline import process_decision; from tests.fixtures.decision_records import valid_decision_record_data; c = connect(':memory:'); o1 = process_decision(c, valid_decision_record_data()); o2 = process_decision(c, valid_decision_record_data()); assert o1 == o2 and o1.order_intent_id == 'oi_dec_001'; n = c.execute('SELECT COUNT(*) FROM status_events').fetchone()[0]; assert n == 4, n"` exits 0
- [ ] `git status --porcelain` shows only the five in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

- `app/state/` already exists with content, or storage/order modules don't
  match the "Current state" interfaces.
- You need to modify schema/policy/orders/storage modules beyond the one
  `_SCHEMA` addition — the existing interfaces are sufficient by design.
- The idempotent-rerun test cannot pass without weakening the storage
  conflict guard — report; do not weaken it.

## Maintenance notes

- Broker adapter work extends `DecisionStatus` (submitted/filled/...) and
  `_LEGAL_TRANSITIONS`; `process_decision` should remain the only writer of
  decision statuses.
- The `status_events` table is the dashboard's workflow-graph data source.
- `record.order_intent_id` on stored records stays None by design; the
  linkage lives in the intent's `decision_id` and the status log
  (append-only rule).
