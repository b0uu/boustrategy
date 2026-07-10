# Plan 003: Add portfolio-aware policy rules (trade quotas, holdings cap, theme concentration) and remove the dead sizing field

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 01193d1..HEAD -- app/policy/ tests/policy/ docs/decision_record.md`
> The implementation baseline was committed as `01193d1` ("schema and policy
> added"). Compare the "Current state" excerpts below against the live code
> before proceeding; on a mismatch, STOP. This plan assumes **plans 001 and
> 002 have already landed** (001 adds `primary_theme_id` to the schema; 002
> rewrites the same policy function this plan extends).

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW (additive: new rules only fire when the new context argument is provided)
- **Depends on**: plans/001-tighten-decision-record-schema.md (hard — reads `primary_theme_id`), plans/002-correct-policy-gate-scoping.md (hard — same function, assumes post-002 shape)
- **Category**: tech-debt
- **Planned at**: commit `d0fc4b2`, 2026-06-12; revised 2026-07-08 after maintainer decisions (baseline now `01193d1`)

## Why this matters

`docs/decision_record.md` lists policy rules that have no implementation:
"reject decisions that exceed daily trade limits" and "reject decisions that
exceed max holdings or theme concentration". They are unimplementable today
because `evaluate_decision_policy(record)` sees only a single record — it has
no portfolio state. This plan introduces an explicit `PortfolioContext`
input and implements the rules with the limits the maintainer decided on
2026-07-08:

- **BUY/ADD quota: 2 per day.** De-risking must never be quota-blocked, so
  TRIM/SELL are exempt from this quota entirely.
- **TRIM/SELL circuit breaker: 10 per day.** Not a strategy limit — a
  malfunction brake against a runaway selling loop. With at most 10
  holdings, a legitimate full-portfolio derisk still fits in one day.
- **Max holdings: 10 (hard).** The ~7-holding portfolio goal is deliberately
  NOT a policy rule — it lives in the mandate/prompt layer where the model
  weighs it. Policy rejects only the 11th position.
- **Primary-theme concentration: 60% max.** No single primary theme may
  exceed 60% of the portfolio after a BUY/ADD. This uses the
  `primary_theme_id` field from plan 001 — each decision names ONE dominant
  theme, which avoids double-counting a ticker that maps to several
  overlapping themes (NVDA → ai_semiconductors + ai_infrastructure +
  ai_bottlenecks would otherwise count three times).

Separately, `PolicyResult.adjusted_final_target_weight` has existed since the
module was written and is never assigned anywhere — callers reading it always
get `None`. The sizing-adjustment behavior it anticipates (spec §12) depends
on inputs that don't exist yet (thesis-quality scoring, liquidity/spread
data), so the field is removed until that behavior can actually be designed.
Dead interface surface on a risk-control API invites callers to trust a value
that is never computed.

## Current state

This plan assumes the post-002 version of `app/policy/decision_policy.py`:

- a module-level `_EXPOSURE_INCREASING = {Decision.BUY, Decision.ADD}` set,
- escalation gates for RED regime / DE_RISKING mode (reason codes
  `buy_or_add_in_red_requires_extraordinary_opportunity` etc.),
- weight caps scoped to `_EXPOSURE_INCREASING`,
- an X gate scoped to actionable + thesis-supporting usage,
- and these unchanged parts from the original (verify still present):

```python
MAX_EQUITY_TARGET_WEIGHT = 0.20
MAX_ETF_TARGET_WEIGHT = 0.50


class PolicyResult(BaseModel):
    approved: bool
    reasons: list[str] = Field(default_factory=list)
    adjusted_final_target_weight: float | None = None
```

Signature:

```python
def evaluate_decision_policy(record: InvestmentDecisionRecord) -> PolicyResult:
```

`_is_actionable` returns True for BUY/ADD/TRIM/SELL.

After plan 001, `InvestmentDecisionRecord` has `primary_theme_id: str | None`
(required for BUY/ADD, must be one of `theme_ids`), and the test fixture's
BUY record carries `primary_theme_id: "ai_semiconductors"`.

Other files:

- `tests/policy/test_decision_policy.py` — all policy tests; every test calls
  `evaluate_decision_policy(record)` with one positional argument.
- `tests/fixtures/decision_records.py` — `decision_record_with(**overrides)`
  builds records.
- `docs/decision_record.md` — "Policy rules" section.

Repo conventions: pydantic models with `ConfigDict(extra="forbid")` for
record-like inputs (see `SourceClaim` in `app/schemas/decision_record.py`
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
- The ~7-holding goal — mandate/prompt content, not policy code.
- Any sizing-adjustment / weight-clamping logic — explicitly deferred.
- `tests/fixtures/decision_records.py`.

## Git workflow

- Branch: `advisor/003-portfolio-aware-policy-rules`
- Commit style: short lowercase imperative summary, matching existing history.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add PortfolioContext and the decided limits

In `app/policy/decision_policy.py`, add next to the existing weight constants:

```python
MAX_BUY_ADD_TRADES_PER_DAY = 2
MAX_SELL_TRIM_TRADES_PER_DAY = 10
MAX_HOLDINGS = 10
MAX_PRIMARY_THEME_WEIGHT = 0.60


class PortfolioContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    holdings_count: int = Field(ge=0)
    buy_add_trades_today: int = Field(ge=0)
    sell_trim_trades_today: int = Field(ge=0)
    # weight of the portfolio in each primary theme, EXCLUDING any existing
    # position in the ticker under evaluation, so an ADD's new target weight
    # can be added without double-counting the position's current weight
    primary_theme_weights: dict[str, float] = Field(default_factory=dict)
```

Add `ConfigDict` to the pydantic import.

**Verify**: `python -c "from app.policy.decision_policy import PortfolioContext; PortfolioContext(holdings_count=5, buy_add_trades_today=0, sell_trim_trades_today=0)"` → exit 0.

### Step 2: Thread the context through evaluation

Change the signature to:

```python
def evaluate_decision_policy(
    record: InvestmentDecisionRecord,
    portfolio: PortfolioContext | None = None,
) -> PolicyResult:
```

Append the four new gates after the existing ones, before the `return`:

```python
    if portfolio is not None:
        if (
            record.decision in _EXPOSURE_INCREASING
            and portfolio.buy_add_trades_today >= MAX_BUY_ADD_TRADES_PER_DAY
        ):
            reasons.append("daily_buy_add_limit_reached")

        if (
            record.decision in {Decision.TRIM, Decision.SELL}
            and portfolio.sell_trim_trades_today >= MAX_SELL_TRIM_TRADES_PER_DAY
        ):
            reasons.append("sell_trim_circuit_breaker_tripped")

        if record.decision == Decision.BUY and portfolio.holdings_count >= MAX_HOLDINGS:
            reasons.append("max_holdings_reached")

        if (
            record.decision in _EXPOSURE_INCREASING
            and record.primary_theme_id is not None
            and portfolio.primary_theme_weights.get(record.primary_theme_id, 0.0)
            + record.final_target_weight
            > MAX_PRIMARY_THEME_WEIGHT
        ):
            reasons.append("primary_theme_concentration_exceeded")
```

Semantics, deliberately chosen by the maintainer (2026-07-08):

- The BUY/ADD quota never touches TRIM/SELL: de-risking is never
  quota-blocked. The separate TRIM/SELL cap exists only as a malfunction
  brake and is sized (10/day) so a full-portfolio derisk fits in one day.
- The holdings cap applies only to BUY because only a new position increases
  the holdings count (ADD/TRIM/SELL/HOLD act on existing positions).
- The theme rule computes prospective concentration: current theme weight
  (excluding this ticker's existing position, per the context field's
  contract) plus this decision's final target weight.
- When `portfolio` is `None` (all current callers), behavior is unchanged.

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
  BUY/ADD once 2 buy-side trades have executed today; TRIM/SELL are never
  quota-blocked but a 10-trade/day circuit breaker exists as a malfunction
  brake (requires portfolio context)."
- Replace "reject decisions that exceed max holdings or theme concentration."
  with "reject BUY at 10 existing holdings — the ~7-holding goal lives in the
  mandate, not policy; reject BUY/ADD that would push a single primary theme
  above 60% of the portfolio (requires portfolio context)."

**Verify**: `git diff docs/decision_record.md` shows only those bullets changed.

## Test plan

New tests in `tests/policy/test_decision_policy.py`, importing
`PortfolioContext` from `app.policy.decision_policy`, modeled after the
existing tests. Use a helper context of
`PortfolioContext(holdings_count=5, buy_add_trades_today=0,
sell_trim_trades_today=0)` and override per test:

1. `test_rejects_buy_when_daily_buy_add_limit_reached` — fixture BUY,
   `buy_add_trades_today=2` → not approved, `"daily_buy_add_limit_reached"`
   in reasons.
2. `test_rejects_add_when_daily_buy_add_limit_reached` — `decision="ADD"`,
   same context → not approved.
3. `test_allows_sell_when_buy_add_limit_reached` — `decision="SELL"`,
   `buy_add_trades_today=2, sell_trim_trades_today=0` → approved (de-risking
   is never quota-blocked).
4. `test_rejects_sell_when_circuit_breaker_tripped` — `decision="SELL"`,
   `sell_trim_trades_today=10` → not approved,
   `"sell_trim_circuit_breaker_tripped"` in reasons.
5. `test_allows_hold_when_all_limits_reached` — `decision="HOLD"`,
   `buy_add_trades_today=2, sell_trim_trades_today=10, holdings_count=10` →
   approved (HOLD executes nothing).
6. `test_rejects_buy_at_max_holdings` — fixture BUY, `holdings_count=10` →
   not approved, `"max_holdings_reached"` in reasons.
7. `test_allows_add_at_max_holdings` — `decision="ADD"`, `holdings_count=10`
   → approved (ADD does not create a new holding).
8. `test_rejects_buy_exceeding_primary_theme_cap` — fixture BUY (final
   weight 0.12, primary theme `ai_semiconductors`),
   `primary_theme_weights={"ai_semiconductors": 0.55}` → not approved,
   `"primary_theme_concentration_exceeded"` in reasons (0.55 + 0.12 > 0.60).
9. `test_allows_buy_within_primary_theme_cap` — same but
   `primary_theme_weights={"ai_semiconductors": 0.40}` → approved
   (0.40 + 0.12 = 0.52, under the 0.60 cap).
10. `test_portfolio_rules_skipped_without_context` — fixture BUY,
    `evaluate_decision_policy(record)` with no second argument → approved.

Verification: `python -m pytest -q` → all pass, 10 new tests included.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `python -m pytest -q` exits 0; 10 new tests present
- [ ] `grep -rn "adjusted_final_target_weight" app/ tests/ docs/` returns no matches
- [ ] `python -c "from tests.fixtures.decision_records import valid_decision_record; from app.policy.decision_policy import evaluate_decision_policy, PortfolioContext; r = evaluate_decision_policy(valid_decision_record(), PortfolioContext(holdings_count=10, buy_add_trades_today=0, sell_trim_trades_today=0)); assert not r.approved and 'max_holdings_reached' in r.reasons"` exits 0
- [ ] `python -c "from tests.fixtures.decision_records import valid_decision_record; from app.policy.decision_policy import evaluate_decision_policy, PortfolioContext; r = evaluate_decision_policy(valid_decision_record(), PortfolioContext(holdings_count=5, buy_add_trades_today=0, sell_trim_trades_today=0, primary_theme_weights={'ai_semiconductors': 0.55})); assert not r.approved and 'primary_theme_concentration_exceeded' in r.reasons"` exits 0
- [ ] `git status --porcelain` shows changes only in the three in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `InvestmentDecisionRecord` has no `primary_theme_id` field — plan 001 has
  not landed.
- The RED-regime gate still reads `record.decision == Decision.BUY` (rather
  than the `_EXPOSURE_INCREASING` escalation gate) — plan 002 has not landed;
  this plan's excerpts assume the post-002 shape.
- `adjusted_final_target_weight` turns out to be read anywhere outside
  `app/policy/decision_policy.py` (it had zero readers at planning time; a
  reader appearing means the codebase drifted).
- Any existing test fails for a reason you cannot trace to steps 2-3.

## Maintenance notes

- **Limits decided 2026-07-08 by the maintainer**: BUY/ADD 2/day; TRIM/SELL
  exempt with a 10/day circuit breaker; 10 holdings hard (goal ~7 in
  mandate/prompts); 60% single-primary-theme cap. When the maintainer writes
  `docs/mandate.md`, the ~7-holding goal and the reasoning behind these
  numbers belong there.
- `PortfolioContext.primary_theme_weights` has a contract the future caller
  (the backend state machine, spec §13) must honor: weights are computed
  EXCLUDING any existing position in the ticker under evaluation. Getting
  this wrong double-counts ADDs. Put a test on the caller when it exists.
- `PortfolioContext` is the seam where future portfolio-derived rules
  attach: exposure-band checks per regime (spec §5 target bands) and sizing
  adjustment (spec §12). When sizing adjustment is designed, reintroduce an
  adjusted-weight field on `PolicyResult` *together with* the code that
  computes it.
- Until the state machine exists, production callers passing `None` silently
  skip these rules — when it is built, make the context argument required at
  that call site.
