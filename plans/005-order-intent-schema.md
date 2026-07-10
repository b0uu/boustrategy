# Plan 005: Add the Order Intent schema and creation from approved decisions

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat e869d55..HEAD -- app/ tests/`
> Compare the "Current state" excerpts below against the live code before
> proceeding; on a mismatch, STOP. This plan assumes **plans 001-003 have
> landed** (stable schema and policy shapes).

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW (purely additive: new module, no existing behavior changes)
- **Depends on**: plans/001, 002, 003 (landed schema/policy shapes)
- **Category**: direction
- **Planned at**: commit `e869d55`, 2026-07-10

## Why this matters

The project's core safety principle is "No direct LLM-to-order path"
(`boustrategy_spec.md` §2). The pipeline is: Decision Record → Schema
Validation → Policy Checks → **Approved Order Intent** → Broker Execution.
Today the pipeline dead-ends after policy: `InvestmentDecisionRecord` has an
`order_intent_id` field pointing at a concept that doesn't exist. This plan
builds the Order Intent object and the single legal way to create one — from
an actionable decision record that passed policy. After this plan, the
safety principle is code, not prose: there is no constructor path from LLM
output to an order intent that skips policy.

Deliberately deferred (do NOT build here): quantity/notional computation
(needs live portfolio value and quotes — broker adapter work), order intent
status transitions beyond creation (state machine work), and persistence
(plan 006).

## Current state

- `app/schemas/decision_record.py` — all record schemas. Conventions to
  match: `StrEnum` for enums, pydantic models with
  `ConfigDict(extra="forbid")`, `AwareDatetime` for timestamps (post-001).
  Key fields on `InvestmentDecisionRecord` used here: `decision_id`,
  `ticker`, `decision` (enum: BUY/ADD/TRIM/SELL/HOLD/PASS/WATCHLIST),
  `final_target_weight`, `order_intent_id` (str | None, stays None in this
  plan — linking happens at persistence/state-machine time).
- `app/policy/decision_policy.py` — post-003 shape:
  `evaluate_decision_policy(record, portfolio=None) -> PolicyResult` where
  `PolicyResult` has `approved: bool` and `reasons: list[str]` (the
  `adjusted_final_target_weight` field was removed by plan 003).
- `tests/fixtures/decision_records.py` — `valid_decision_record()` (an
  approved-quality BUY) and `decision_record_with(**overrides)`.
- No `app/orders/` package exists.
- Strategy context the code must honor (from `docs/decision_record.md` and
  `boustrategy_spec.md` §12): default order type is LIMIT; market orders are
  the exception, never the default.

Repo conventions: crash early (invalid transitions raise, no None-returns
that hide errors); no premature abstractions; "why" comments only; tests are
plain pytest functions, arrange/act/assert, mirroring `app/` layout under
`tests/`.

## Commands you will need

| Purpose | Command                           | Expected on success |
|---------|-----------------------------------|---------------------|
| Install | `python -m pip install -e .[dev]` | exit 0              |
| Tests   | `python -m pytest -q`             | all pass, exit 0    |
| Lint*   | `python -m ruff check .`          | exit 0              |
| Types*  | `python -m mypy app tests`        | exit 0              |

*Only if plan 004 has landed (check: `grep -q "\[tool.ruff\]" pyproject.toml`).

## Scope

**In scope** (the only files you should create/modify):

- `app/schemas/order_intent.py` (create)
- `app/orders/__init__.py` (create, empty)
- `app/orders/create_order_intent.py` (create)
- `tests/orders/__init__.py` (create, empty)
- `tests/orders/test_create_order_intent.py` (create)

**Out of scope** (do NOT touch):

- `app/schemas/decision_record.py` and `app/policy/decision_policy.py` —
  read-only inputs to this plan.
- Broker/quantity/notional logic, status transitions, persistence.
- `docs/` — no doc changes in this plan.

## Git workflow

- Branch: `advisor/005-order-intent-schema`
- Commit style: short lowercase imperative summary, matching existing history.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Create the OrderIntent schema

Create `app/schemas/order_intent.py`:

```python
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


class OrderIntentStatus(StrEnum):
    CREATED = "CREATED"


class OrderIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_intent_id: str = Field(min_length=1)
    decision_id: str = Field(min_length=1)
    created_at: AwareDatetime
    ticker: str = Field(min_length=1, max_length=12)
    side: OrderSide
    order_type: OrderType = OrderType.LIMIT
    target_weight: float = Field(ge=0.0, le=1.0)
    status: OrderIntentStatus = OrderIntentStatus.CREATED
```

`OrderIntentStatus` has one value on purpose: the broker-adapter phase adds
the execution statuses (spec §13 lists them); creating them now would imply
transitions that don't exist.

**Verify**: `python -c "from app.schemas.order_intent import OrderIntent, OrderSide, OrderType, OrderIntentStatus"` → exit 0.

### Step 2: Create the single legal constructor

Create `app/orders/create_order_intent.py`:

```python
from datetime import UTC, datetime

from pydantic import AwareDatetime

from app.policy.decision_policy import PolicyResult
from app.schemas.decision_record import Decision, InvestmentDecisionRecord
from app.schemas.order_intent import OrderIntent, OrderSide

_INTENT_SIDES = {
    Decision.BUY: OrderSide.BUY,
    Decision.ADD: OrderSide.BUY,
    Decision.TRIM: OrderSide.SELL,
    Decision.SELL: OrderSide.SELL,
}


def create_order_intent(
    record: InvestmentDecisionRecord,
    policy_result: PolicyResult,
    created_at: AwareDatetime | None = None,
) -> OrderIntent:
    if not policy_result.approved:
        raise ValueError("cannot create an order intent from a rejected decision")

    side = _INTENT_SIDES.get(record.decision)
    if side is None:
        raise ValueError(
            f"decision {record.decision} is not actionable and cannot produce an order intent"
        )

    return OrderIntent(
        order_intent_id=f"oi_{record.decision_id}",
        decision_id=record.decision_id,
        created_at=created_at or datetime.now(UTC),
        ticker=record.ticker,
        side=side,
        target_weight=record.final_target_weight,
    )
```

Design notes (the "why", for the reviewer):

- The intent id is derived deterministically from the decision id
  (`oi_<decision_id>`): one decision can only ever name one intent, which is
  the idempotency foundation the spec (§13) requires — re-running the
  creation after a crash produces the same id, so persistence (plan 006) can
  treat duplicates as no-ops.
- Rejection and non-actionable decisions raise instead of returning None:
  crash early is the repo convention, and a silent None here is exactly how
  an unapproved decision could slip toward execution unnoticed.
- `order_type` defaults to LIMIT per the spec's execution policy.

**Verify**: `python -m pytest -q` → existing tests still pass.

### Step 3: Write the tests

Create `tests/orders/test_create_order_intent.py` per the Test plan below.

**Verify**: `python -m pytest tests/orders -q` → all new tests pass.

## Test plan

In `tests/orders/test_create_order_intent.py`, using
`valid_decision_record()` / `decision_record_with(...)` from
`tests.fixtures.decision_records` and a helper
`approved = PolicyResult(approved=True)`:

1. `test_approved_buy_creates_buy_intent` — fixture BUY → intent with
   `side == OrderSide.BUY`, `ticker == "NVDA"`,
   `target_weight == record.final_target_weight`,
   `order_type == OrderType.LIMIT`, `status == OrderIntentStatus.CREATED`.
2. `test_intent_id_is_deterministic` — two calls on the same record produce
   the same `order_intent_id == "oi_dec_001"`.
3. `test_trim_creates_sell_intent` — `decision="TRIM"` → `side == SELL`.
4. `test_sell_creates_sell_intent` — `decision="SELL"` → `side == SELL`.
5. `test_rejected_decision_raises` —
   `PolicyResult(approved=False, reasons=["x"])` → `pytest.raises(ValueError)`.
6. `test_hold_raises` — `decision="HOLD"` with approved result →
   `pytest.raises(ValueError)` (non-actionable decisions never produce
   intents). Note: build the HOLD record with weights set to the fixture's
   existing values; HOLD does not require escalation fields.
7. `test_created_at_is_timezone_aware` — default-created intent has
   `created_at.tzinfo is not None`.

Verification: `python -m pytest -q` → all pass, 7 new tests included.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `python -m pytest -q` exits 0; 7 new tests in `tests/orders/`
- [ ] `python -c "from tests.fixtures.decision_records import valid_decision_record; from app.policy.decision_policy import PolicyResult; from app.orders.create_order_intent import create_order_intent; i = create_order_intent(valid_decision_record(), PolicyResult(approved=True)); assert i.order_intent_id == 'oi_dec_001' and i.side == 'BUY'"` exits 0
- [ ] `python -c "from tests.fixtures.decision_records import valid_decision_record; from app.policy.decision_policy import PolicyResult; from app.orders.create_order_intent import create_order_intent; create_order_intent(valid_decision_record(), PolicyResult(approved=False, reasons=['r']))"` exits non-zero
- [ ] If plan 004 landed: `python -m ruff check .` and `python -m mypy app tests` exit 0
- [ ] `git status --porcelain` shows only the five in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `PolicyResult` still has an `adjusted_final_target_weight` field (plan 003
  has not landed; this plan assumes the post-003 shape).
- `app/orders/` already exists with content.
- You find yourself needing to modify `decision_record.py` or
  `decision_policy.py` — the interfaces there are sufficient by design;
  needing changes means an assumption is wrong.

## Maintenance notes

- The `order_intent_id` derivation (`oi_<decision_id>`) is a contract:
  persistence (plan 006) relies on it for idempotent inserts, and the future
  state machine relies on it for crash recovery. Changing the derivation
  later invalidates stored intents.
- When the broker adapter lands, `OrderIntentStatus` grows the execution
  statuses and a transition function; `create_order_intent` should remain
  the only way to mint a CREATED intent.
- Quantity/notional computation deliberately absent: the state machine will
  compute it from live portfolio value at execution time, not at decision
  time (weights, not dollars, are the decision-layer language).
