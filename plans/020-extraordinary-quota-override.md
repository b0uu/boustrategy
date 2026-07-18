# Plan 020: Extraordinary-opportunity override for the BUY/ADD daily quota

> Executor instructions: follow exactly; verify each step; STOP on
> mismatch. Branch `advisor/020-extraordinary-quota-override`, do NOT
> push, don't touch plans/README.md. Never edit maintainer-owned docs
> (`docs/risk_policy.md` etc.) — this plan is GATED on the maintainer
> having amended one first (see STOP conditions).

## Status

- Priority P2. Effort S. Depends on nothing in code; gated on a
  maintainer doc amendment. Planned at local main `a97a85f`, 2026-07-18.

## Why this matters

Maintainer direction (2026-07-18): in a fast catalyst burst (the Kimi-K3
example), the flat BUY/ADD 2/day quota could block a genuinely warranted
third entry. Rather than raising the quota, extend the existing
extraordinary-opportunity escalation — the same mechanism that lets a
flagged BUY through RED regimes — to the daily quota, bounded by a new
absolute malfunction brake. The safety property changes from "never more
than 2 BUY/ADD per day" to "exceeding 2 requires a recorded
extraordinary claim, absolute ceiling 5". Abuse is observable: the
extraordinary-bar frequency metric is already a planned eval
(`docs/risk_policy.md`, "Extraordinary opportunities").

Also per the 2026-07-18 session: frequency loosening beyond this is an
evidence-gated posture change (paper-capsule results), never a response
to agent self-assessment. This plan is deliberately the minimal version.

## Current state (local main `a97a85f`)

- `app/policy/decision_policy.py`: constants
  `MAX_BUY_ADD_TRADES_PER_DAY = 2`, `MAX_SELL_TRIM_TRADES_PER_DAY = 10`;
  `evaluate_decision_policy` appends `daily_buy_add_limit_reached` when
  `portfolio.buy_add_trades_today >= MAX_BUY_ADD_TRADES_PER_DAY` for
  BUY/ADD, with no extraordinary exception. The RED-regime and
  de-risking gates already honor `record.extraordinary_opportunity`.
- `app/schemas/decision_record.py`: `InvestmentDecisionRecord` carries
  `extraordinary_opportunity` + justification fields (plan 001). VERIFY
  before coding: the schema rejects
  `extraordinary_opportunity=True` with an empty justification — the
  override leans on that invariant. If it doesn't, STOP (that's a plan
  001 regression, not something to patch here silently).
- `docs/risk_policy.md` table row: `| BUY/ADD trades per day | 2 |
  BUY/ADD only |` — the amendment below must land first.

## Required maintainer amendment (prerequisite, not executor work)

`docs/risk_policy.md` quota row replaced with words to this effect:

> BUY/ADD trades per day: 2; a declared `extraordinary_opportunity`
> (with written justification) may exceed the quota, subject to an
> absolute circuit breaker of 5 BUY/ADD per day that no declaration can
> exceed.

## Design

In `app/policy/decision_policy.py`:

- New constant `MAX_BUY_ADD_TRADES_PER_DAY_BRAKE = 5`.
- Quota check becomes: for BUY/ADD with portfolio context,
  - `buy_add_trades_today >= MAX_BUY_ADD_TRADES_PER_DAY_BRAKE` →
    `buy_add_circuit_breaker_tripped` (unconditional — extraordinary
    flag does NOT bypass);
  - else `buy_add_trades_today >= MAX_BUY_ADD_TRADES_PER_DAY` and not
    `record.extraordinary_opportunity` →
    `daily_buy_add_limit_reached` (unchanged reason string).
- Everything else in the function unchanged. All other caps (sizing,
  holdings, theme concentration) continue to apply to extraordinary
  trades — consistent with the risk-policy doctrine that extraordinary
  trades get full normal caps, no special sizing.

## Steps

1. Verify the schema invariant named in Current state.
2. Implement; update tests in the mirrored policy test module:
   - 3rd BUY today without flag → rejected `daily_buy_add_limit_reached`.
   - 3rd BUY today with flag + justification → approved (assuming no
     other violations).
   - 5th trade of the day (i.e. `buy_add_trades_today = 5`) with flag →
     rejected `buy_add_circuit_breaker_tripped`.
   - TRIM/SELL paths unaffected (existing tests still green).
   - Flagged BUY in RED over the brake → BOTH the brake reason and no
     regression of the RED gate logic.
3. Gates: pytest -q, ruff check, ruff format --check, mypy app tests →
   all exit 0; `git status --porcelain` clean after commit.

## STOP conditions

- `docs/risk_policy.md` does not yet contain the extraordinary-override
  clause for the daily quota — the code must never be more permissive
  than the maintainer-owned policy doc.
- The schema does not enforce justification-with-flag (see Current
  state).
- Current-state signatures don't match local main.

## Maintenance notes

- When the extraordinary-frequency eval exists, quota-override uses are
  exactly the records with `extraordinary_opportunity=True` that ALSO
  hit `buy_add_trades_today >= 2` — derivable from decision records +
  status events; no extra instrumentation added here on purpose.
- If evals later justify a higher base quota, that is a
  `docs/risk_policy.md` + constant change, not a design change.
