# Plan 003: Add portfolio-aware policy rules (daily trade limit, max holdings) and remove the dead sizing field

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat d0fc4b2..HEAD -- app/policy/ tests/policy/ docs/decision_record.md`
> NOTE: at planning time (2026-06-12), `app/` and `tests/` were **untracked**
> in git, so this diff may be empty even if files changed. The authoritative
> drift reference is the "Current state" excerpts below — compare them against
> the live code before proceeding; on a mismatch, STOP. This plan assumes
> **plan 002 has already landed** (it rewrites the same function).

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW (additive: new rules only fire when the new context argument is provided)
- **Depends on**: plans/002-correct-policy-gate-scoping.md
- **Category**: tech-debt
- **Planned at**: commit `d0fc4b2`, 2026-06-12

## Why this matters

`docs/decision_record.md` lists two policy rules that have no implementation:
"reject decisions that exceed daily trade limits" and "reject decisions that
exceed max holdings or theme concentration". They are unimplementable today
because `evaluate_decision_policy(record)` sees only a single record — it has
no portfolio state. The spec defines the numbers (`boustrategy_spec.md` §12,
"Initial limits"): **max executed trades/day: 2** and **max holdings: 3-6**
(6 is the hard ceiling). This plan introduces an explicit `PortfolioContext`
input and implements both rules.

Separately, `PolicyResult.adjusted_final_target_weight` has existed since the
module was written and is never assigned anywhere — callers reading it always
get `None`. The sizing-adjustment behavior it anticipates (spec §12 "Sizing
adjustment") depends on inputs that don't exist yet (thesis quality scoring,
liquidity/spread data), so the field is removed until that behavior can
actually be designed. Dead interface surface on a risk-control API invites
callers to trust a value that is never computed.

Theme concentration is **deliberately not implemented** here: the spec defines
no numeric theme limit anywhere (§12 lists none; §17 "Open questions" still
lists initial sizes as open). Inventing a number is the maintainer's call,
not the executor's.

## Current state

This plan assumes plan 002's version of `app/policy/decision_policy.py`:
gates for RED/DE_RISKING and weight caps scoped to `{Decision.BUY,
Decision.ADD}` via an `_EXPOSURE_INCREASING` set, an X gate scoped to
actionable + thesis-supporting usage, and these unchanged parts from the
original (verify they are still present):

`app/policy/decision_policy.py:6-13` (pre-plan-002 line numbers):

```python
MAX_EQUITY_TARGET_WEIGHT = 0.20
MAX_ETF_TARGET_WEIGHT = 0.50


class PolicyResult(BaseModel):
    approved: bool
    reasons: list[str] = Field(default_factory=list)
    adjusted_final_target_weight: float | None = None
```

`evaluate_decision_policy` signature (pre-plan-002 line 16):

```python
def evaluate_decision_policy(record: InvestmentDecisionRecord) -> PolicyResult:
```

`_is_actionable` (pre-plan-002 lines 49-55) returns True for
BUY/ADD/TRIM/SELL.

Other files:

- `tests/policy/test_decision_policy.py` — all policy tests; every test calls
  `evaluate_decision_policy(record)` with one positional argument.
- `tests/fixtures/decision_records.py` — `decision_record_with(**overrides)`
  builds records.
- `docs/decision_record.md` — "Policy rules" section.

Repo conventions: pydantic models with `ConfigDict(extra="forbid")` for
record-like inputs (see `SourceClaim` in `app/schemas/decision_record.py:42-50`
as the exemplar); crash early; no premature abstractions; policy reasons are
lowercase snake_case strings; plain pytest functions in arrange/act/assert
style.

## Commands you will need

| Purpose | Command                           | Expected on success |
|---------|-----------------------------------|---------------------|
| Install | `python -m pip install -e .[dev]` | exit 0              |
| Tests   | `python -m pytest -q`             | all pass, exit 0    |

## Scope

**In scope** (the only files you should modify):

- `app/policy/decision_policy.py`
- `tests/policy/test_decision_policy.py`
- `docs/decision_record.md` (the "Policy rules" section only)

**Out of scope** (do NOT touch, even though they look related):

- `app/schemas/decision_record.py` — `PortfolioContext` is a policy input,
  not a decision-record schema; it lives in the policy module.
- Theme concentration limits — no number exists in the spec; do not invent one.
- Any sizing-adjustment / weight-clamping logic — explicitly deferred.
- `tests/fixtures/decision_records.py`.

## Git workflow

- Branch: `advisor/003-portfolio-aware-policy-rules`
- Commit style: short lowercase imperative summary, matching existing history.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add PortfolioContext and limits

In `app/policy/decision_policy.py`, add next to the existing weight constants:

```python
MAX_EXECUTED_TRADES_PER_DAY = 2
MAX_HOLDINGS = 6


class PortfolioContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    holdings_count: int = Field(ge=0)
    executed_trades_today: int = Field(ge=0)
```

Add `ConfigDict` to the pydantic import.

**Verify**: `python -c "from app.policy.decision_policy import PortfolioContext; PortfolioContext(holdings_count=3, executed_trades_today=0)"` → exit 0.

### Step 2: Thread the context through evaluation

Change the signature to:

```python
def evaluate_decision_policy(
    record: InvestmentDecisionRecord,
    portfolio: PortfolioContext | None = None,
) -> PolicyResult:
```

Append the two new gates after the existing ones, before the `return`:

```python
    if (
        portfolio is not None
        and _is_actionable(record)
        and portfolio.executed_trades_today >= MAX_EXECUTED_TRADES_PER_DAY
    ):
        reasons.append("daily_trade_limit_reached")

    if (
        portfolio is not None
        and record.decision == Decision.BUY
        and portfolio.holdings_count >= MAX_HOLDINGS
    ):
        reasons.append("max_holdings_reached")
```

Semantics, deliberately chosen: the trade limit applies to every decision
that would execute a trade (BUY/ADD/TRIM/SELL); the holdings cap applies only
to BUY because only a new position increases the holdings count (ADD/TRIM/
SELL/HOLD act on existing positions). When `portfolio` is `None` (all current
callers), behavior is unchanged.

**Verify**: `python -m pytest -q` → all existing tests still pass.

### Step 3: Remove the dead sizing field

Delete `adjusted_final_target_weight: float | None = None` from
`PolicyResult`.

**Verify**: `grep -rn "adjusted_final_target_weight" app/ tests/ docs/` →
no matches. `python -m pytest -q` → all pass.

### Step 4: Add tests

Append the tests in "Test plan" to `tests/policy/test_decision_policy.py`.

**Verify**: `python -m pytest -q` → all pass.

### Step 5: Update the policy rules doc

In `docs/decision_record.md` under `## Policy rules`:

- Replace "reject decisions that exceed daily trade limits." with "reject
  actionable decisions once 2 trades have already executed today (requires
  portfolio context)."
- Replace "reject decisions that exceed max holdings or theme concentration."
  with "reject BUY at 6 or more existing holdings (requires portfolio
  context). Theme concentration limits are not yet defined."

**Verify**: `git diff docs/decision_record.md` shows only those bullets changed.

## Test plan

New tests in `tests/policy/test_decision_policy.py`, importing
`PortfolioContext` from `app.policy.decision_policy`, modeled after the
existing tests:

1. `test_rejects_buy_when_daily_trade_limit_reached` — fixture BUY,
   `PortfolioContext(holdings_count=3, executed_trades_today=2)` → not
   approved, `"daily_trade_limit_reached"` in reasons.
2. `test_rejects_sell_when_daily_trade_limit_reached` — `decision="SELL"`,
   same context → not approved (the limit governs all executed trades, not
   just buys).
3. `test_allows_hold_when_daily_trade_limit_reached` — `decision="HOLD"`,
   same context → approved (HOLD executes nothing).
4. `test_rejects_buy_at_max_holdings` — fixture BUY,
   `PortfolioContext(holdings_count=6, executed_trades_today=0)` → not
   approved, `"max_holdings_reached"` in reasons.
5. `test_allows_add_at_max_holdings` — `decision="ADD"`, same context →
   approved (ADD does not create a new holding).
6. `test_portfolio_rules_skipped_without_context` — fixture BUY,
   `evaluate_decision_policy(record)` with no second argument → approved.

Verification: `python -m pytest -q` → all pass, 6 new tests included.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `python -m pytest -q` exits 0; 6 new tests present
- [ ] `grep -rn "adjusted_final_target_weight" app/ tests/ docs/` returns no matches
- [ ] `python -c "from tests.fixtures.decision_records import valid_decision_record; from app.policy.decision_policy import evaluate_decision_policy, PortfolioContext; r = evaluate_decision_policy(valid_decision_record(), PortfolioContext(holdings_count=6, executed_trades_today=0)); assert not r.approved and 'max_holdings_reached' in r.reasons"` exits 0
- [ ] `git status --porcelain` shows changes only in the three in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `app/policy/decision_policy.py` does not exist in your working copy (the
  implementation was untracked at planning time).
- Plan 002 has not landed (the RED-regime gate still reads
  `record.decision == Decision.BUY` rather than a BUY+ADD set) — this plan's
  excerpts assume the post-002 shape.
- `adjusted_final_target_weight` turns out to be read anywhere outside
  `app/policy/decision_policy.py` (it had zero readers at planning time; a
  reader appearing means the codebase drifted).
- Any existing test fails for a reason you cannot trace to steps 2-3.

## Maintenance notes

- `PortfolioContext` is the seam where future portfolio-derived rules attach:
  theme concentration (once the maintainer defines a limit), exposure-band
  checks per regime (spec §5 target bands), and sizing adjustment (spec §12).
  When sizing adjustment is designed, reintroduce an adjusted-weight field on
  `PolicyResult` *together with* the code that computes it.
- The caller that will populate `PortfolioContext` (the backend state
  machine, spec §13) does not exist yet. Until it does, production callers
  passing `None` silently skip these rules — when the state machine is
  built, make the context argument required at that call site.
- MAX_HOLDINGS uses 6, the top of the spec's "3-6" range, as the hard
  ceiling; the 3-position floor is a portfolio-construction goal, not a
  reject rule.
