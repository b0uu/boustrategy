# Investment Decision Record 

This document is a guideline for the structured artificat that should be produced after each decision workflow. Designed to be evaluated deterministically in order to set clear standards for certain decisions.

Simple model:

Model reasoning -> Formatted to decision record -> schema validation -> policy evaluation -> decision approval/rejection

Pydantic should validate shape, types, enum values, required fields, and local
field consistency. The policy engine should decide whether a valid record is
allowed under BouStrategy rules.

## Schema layer vs policy layer

The schema layer acts like a parser, validates formatting, policy layer validates adherence to the rules of our harness, for example, max trade size in a given state.

Example:

```json
{
  "ticker": "NVDA",
  "asset_type": "EQUITY",
  "decision": "BUY",
  "regime_state": "RED",
  "final_target_weight": 0.12
}
```
This would be valid schema but rejected due to policy evaluation.

## Fields

- `decision_id`: key for certain decision.
- `created_at`: timestamp.
- `ticker`: should be uppercase
- `asset_type`: prevents assets other than equities and ETFs
- `decision`: limited to allowed decision vocabulary
- `theme_ids`: maps the decision to the theme
- `strategy_belief_ids`: maps the decision to the written strategy factors
- `trigger_id`: connects the decision back to the reason it was considered.
- `operating_mode`: tells policy whether system is deploying, managing, or de-risking.
- `regime_state`: drives exposure and buy restrictions
- `source_pack_id`: connects the decision to the evidence bundle
- `initial_thesis`: initial thesis prior to revision
- `counter_thesis`: objection to initial thesis
- `adversarial_refinement`: how the thesis changed after criticism
- `refined_thesis`: final reasoning used for the actual decision.
- `what_is_priced_in`: forces market-expectations reasoning
- `thesis_invalidation_criteria`: required to provide invalidation case for each decision, enforced by policy
- `add_conditions`: when to increase exposure
- `trim_conditions`: when to reduce exposure
- `exit_conditions`: when to sell
- `proposed_target_weight`: proposed size
- `final_target_weight`: final size
- `entry_price_max`: highest price at which a BUY or ADD thesis still holds. Live execution
  refuses the packet when the ask is above it, so an idea that gets priced in between
  authoring and placement stops instead of being chased. Required on every live buy.
- `entry_price_min`: the same bound for a SELL or TRIM, checked against the bid.
- `source_claims`: specific claims tied to source IDs and timestamps
- `x_signal_usage`: records whether X influenced the decision and whether it was confirmed outside X.
- `public_summary`: summary for public dashboard
- `internal_notes`: private internal notes (might choose not to differentiate public from private later on)
- `order_intent_id`: null until policy creates an order intent.
- `broker_execution_record_id`: null until execution occurs

## Schema rules
- enum values are valid
- weights are between 0 and 1
- ticker is trimmed and uppercased, contains 1-12 characters from `A-Z`, digits, `.`, or `-`, and starts with a letter
- timestamps are timezone-aware
- source claim `source_type` is limited to the source vocabulary
- source claim confidence is between 0 and 1
- final target weight does not exceed proposed target weight
- actionable decisions have a refined thesis
- SHORT_WATCHLIST decisions have a refined thesis, counter-thesis, and `what_is_priced_in`, and both target weights are 0
- SHORT_WATCHLIST_REMOVE decisions explain the removal in `refined_thesis`, and both target weights are 0
- SHORT_WATCHLIST decisions carry `short_removal_conditions` (`cover_below`, `stop_above`, `review_by`); every other decision omits it
- `cover_below` < `reference_price` < `stop_above`, and `review_by` falls after the record's creation date
- X usage fields are internally consistent across `used`, `usage_type`, and `confirmed_outside_x`
- `extraordinary_opportunity=true` requires a non-empty `extraordinary_justification`
- `primary_theme_id` must be one of `theme_ids` and is required for BUY and ADD

## Policy rules
- reject BUY or ADD in RED unless the record declares an extraordinary opportunity with justification.
- reject BUY or ADD in DE_RISKING mode unless the record declares an extraordinary opportunity with justification.
- reject BUY or ADD with stock target weight above 20%.
- reject BUY or ADD with ETF target weight above 50%.
- reject BUY or ADD without strategy belief IDs.
- reject actionable and SHORT_WATCHLIST decisions without invalidation criteria.
- reject actionable and SHORT_WATCHLIST decisions without source claims.
- reject actionable and SHORT_WATCHLIST decisions whose thesis used X (idea source or confirmation) without outside-X confirmation.
- SHORT_WATCHLIST is a recommendation for a short the account cannot take; it never creates an order intent.
- reject SHORT_WATCHLIST_REMOVE for a ticker that isn't on the short watchlist (requires portfolio context).
- reject SHORT_WATCHLIST whose `review_by` is more than 30 days after the record's creation date.
- reject WATCHLIST for a ticker already on the watchlist unless `entry_price_max` differs from its latest statement (requires portfolio context).

## Short watchlist history

The short watchlist is not stored separately. `app/storage/short_watchlist.py`
rebuilds it from policy-approved records for one execution mode: a call opens at
its first SHORT_WATCHLIST, collects every later SHORT_WATCHLIST for that ticker
as a dated declaration with its reference price, and closes at a
SHORT_WATCHLIST_REMOVE with that record's date and price. A later
SHORT_WATCHLIST opens a new call.

Each declaration carries the removal conditions recorded with it, and the latest
declaration governs. `short_removal_status` names every condition an open call
has already met — `cover_below_hit`, `stop_above_hit`, `review_by_reached` —
judged on completed daily closes rather than intraday touches, so the answer does
not depend on when the harness looked. A due call raises a `short_removal_due`
trigger, is flagged REMOVAL DUE in the intake, and a review that neither removes
nor re-underwrites it is rejected as an unanswered call.
- reject BUY/ADD once 2 buy-side trades have executed today; TRIM/SELL are never quota-blocked but a 10-trade/day circuit breaker exists as a malfunction brake (requires portfolio context).
- reject BUY at 10 existing holdings — the ~7-holding goal lives in the mandate, not policy; reject BUY/ADD that would push a single primary theme above 60% of the portfolio (requires portfolio context).

## Tests to make

Schema:
- unknown `decision` fails validation.
- unknown `regime_state` fails validation.
- `final_target_weight > proposed_target_weight` fails validation
- actionable decision without `refined_thesis` fails validation
- X usage with `used=true` and empty summary fails validation

Policy:

- valid BUY in GREEN is approved
- BUY in RED is rejected
- BUY with no invalidation criteria is rejected
- BUY with no source claims is rejected
- EQUITY above 20% target weight is rejected
- ETF above 50% target weight is rejected
- BUY with no strategy belief IDs is rejected
- X-used decision without outside-X confirmation is rejected
