# Plan 041: Short watchlist removal monitor, report and dashboard view

## Status

- **Priority**: P1 · **Effort**: M-L · **Risk**: MEDIUM (adds a gate to live reviews)
- **Depends on**: the short watchlist change (SHORT_WATCHLIST, SHORT_WATCHLIST_REMOVE,
  `app/storage/short_watchlist.py`) being committed first. It was uncommitted on `main` at
  `a358580` when this plan was written.
- **Planned at**: `a358580` plus that uncommitted tree, 2026-09-14
- **Build**: not yet (maintainer, 2026-09-14)

## Why

The agent can now declare a short it can't trade (`SHORT_WATCHLIST`) and end it
(`SHORT_WATCHLIST_REMOVE`). `short_watchlist_history()` rebuilds each call's declaration and
removal dates and prices from approved records.

Removal depends on the agent remembering. Nothing records *when* a call should end, nothing checks
prices against it, and a call left open quietly distorts its scored result. The maintainer wants
three things:

1. Removal conditions recorded with every short call, so the agent can monitor them and always
   removes a call when it's time.
2. A report of each call's dates, prices and result, for performance tracking.
3. A short watchlist view on the public dashboard.

## Current state (verified 2026-09-14)

- `InvestmentDecisionRecord` (`app/schemas/decision_record.py`) has no structured removal
  conditions. A SHORT_WATCHLIST carries text `thesis_invalidation_criteria`, `entry_price_min`
  and `reference_price`/`reference_price_at`.
- `app/storage/short_watchlist.py` returns `ShortCall` → `ShortDeclaration` (decision id, date,
  reference price, invalidation text), filtered by execution mode and profile.
- The intake (`app/reason/intake.py`, "## Short watchlist") lists open calls with their dates and
  invalidation criteria. Nothing marks a call as due for removal.
- `prepare()` in `app/reason/run.py:114-116` refreshes prices, earnings and triggers only for
  `docs/watchlist.md`, paper positions and pending intents. **Short tickers get no price bars and
  no triggers.**
- Triggers (`app/triggers/evaluate.py`, `app/triggers/store.py`) are deterministic
  price_move / volume_spike / calendar_upcoming / digest_headline rows. The id is
  `type:subject:date`, and a trigger is `pending` until consumed or expired after 5 days.
- The worker's hunt gate (`hunt_shortfall` in `app/reason/worker.py`) already rejects a review once
  with a named shortfall, retries, then fails `insufficient_research`. That is the enforcement
  pattern to reuse.
- Public dashboard: `app/public/publication.py` projects the source DB into
  `data/boustrategy.public.db`. `app/public/server.py` serves `/api/public/v2/...`, and
  `public-ui/src/App.tsx:28` has `TABS = ['feed', 'positions', 'policies']`. `Positions.tsx` is the
  closest model for a new tab. `public-ui/fixtures/generate.py` and `routes.mjs` feed the UI tests.
- **Public safety:** `thesis_invalidation_criteria`, `refined_thesis` and `internal_notes` are
  private. Public prose comes only from an approved `public_narrative` (whose `conditions` include
  `invalidation`). Numbers such as prices and dates are safe.

## Invariants

- A short call never creates an order intent or broker activity.
- Short-call dates and prices come only from policy-approved decision records. No mutable
  "short list" table becomes the source of truth. A public table may cache the projection.
- Paper and live calls never mix, and live calls are scoped by execution profile.
- Nothing private reaches the public DB.
- Enforcement is deterministic code, not prompt wording alone.

## Steps

### 1. Structured removal conditions on the record

Add an optional model to `app/schemas/decision_record.py`:

```python
class ShortRemovalConditions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cover_below: float = Field(gt=0)   # thesis played out: the price target
    stop_above: float = Field(gt=0)    # price that proves the short wrong
    review_by: date                    # the latest date the call may stay open unreviewed
```

Add a `short_removal_conditions: ShortRemovalConditions | None = None` field to
`InvestmentDecisionRecord`.

Schema rules (local consistency only):
- It is required on SHORT_WATCHLIST and forbidden on every other decision.
- `cover_below < reference_price < stop_above` whenever `reference_price` is set.
- `review_by` falls after `created_at`'s date.

The maximum `review_by` horizon is a posture dial. Add a "Short ideas" line to
`docs/risk_posture.md` (maintainer decision below; proposed default 60 calendar days) and enforce it
in **policy** as a new rule `short_review_horizon_exceeded`. Add the rule to `app/policy/catalog.py`
and bump the check-count assertion in `tests/state/test_policy_ledger.py`.

`ShortDeclaration` in `app/storage/short_watchlist.py` gains `removal_conditions`. The latest
declaration's conditions govern an open call.

### 2. Keep short tickers priced

In `prepare()` (`app/reason/run.py`), add every open short ticker, from both the PAPER history and
each enabled live profile, to `tracked_tickers`. Prices, earnings and triggers then refresh for them.
Add a test that an open short ticker is refreshed and a removed one isn't.

### 3. Deterministic removal monitor

Add a pure evaluator next to the history, `short_removal_status(call, latest_close, on_date)`. It
returns the due conditions: `cover_below_hit` (close ≤ cover_below), `stop_above_hit`
(close ≥ stop_above) and `review_by_reached` (on_date ≥ review_by), with the close and its date.

In `evaluate_triggers`, for every open call with a completed-session bar, insert a
`short_removal_due` trigger (subject = ticker, event date = the bar date) with the due conditions
and the governing declaration id. Keep the existing TTL behavior.

### 4. Intake shows what is due

In the intake's "## Short watchlist" section, print each call's removal conditions and latest close.
Mark a due call on its own line:
`- REMOVAL DUE (stop_above_hit: close 131.20 ≥ 130.00)`.
Tell the agent, in `_AUTHORING_CONTRACT` (`app/reason/worker.py`) and `docs/prompts/daily_management.md`,
that a due call must be answered in the same review.

### 5. Enforce the answer in the worker

Extend the review gate (the `hunt_shortfall` pattern) with a due-call check. The worker computes due
calls from the database at attempt time (`short_watchlist_history` plus the latest cached close),
not from the intake text. For every due ticker, the output must contain one of:

- a `SHORT_WATCHLIST_REMOVE` for that ticker; or
- a fresh `SHORT_WATCHLIST` reaffirmation with **new** removal conditions under which the call is
  no longer due. Reaffirming a due call is allowed at most once per call, mirroring the mandate's
  one re-underwrite rule (maintainer decision below).

Anything else is rejected with a named shortfall (`short call NVDA is due for removal
(stop_above_hit) and was not removed or re-underwritten`), retried once, then failed. Consume the
matching `short_removal_due` triggers when the answering record is submitted.

Do this in live **and** closed-market reviews: removals don't trade, so the after-hours close review
is a good place to catch them.

### 6. Performance report (CLI, JSON-first)

Add `python -m app.reason.run shorts --mode live|paper [--profile codex] [--json]`. It is read-only.
For each call, print:

- ticker, call status (open / removed), first and latest declaration dates, removal date
- declaration reference price, end price (removal `reference_price`, or the latest cached close for
  open calls) and the end price's date
- **short return** = (declaration price − end price) / declaration price, from the first
  declaration, plus the same from the latest declaration
- days on the list, and QQQ's return over the same window as a benchmark
- current removal conditions and due status
- the decision ids behind every date

Summary: count, hit rate (short return > 0), average and median short return, and average return
versus QQQ. Build the computation as a function the dashboard step reuses (the third caller is the
publication step, so this is not a premature abstraction).

### 7. Public dashboard view

**Publication** (`app/public/publication.py`): add
`public_short_calls(portfolio_id TEXT, call_key TEXT, ticker TEXT, status TEXT, content TEXT,
PRIMARY KEY(portfolio_id, call_key))`, and rebuild it on each publish for the live profile/account
and for paper. `call_key` is the first declaration's public id. `content` holds only public-safe
fields:
- ticker and company name (from `public_narrative`)
- declaration and removal dates, reference prices and the short return from step 6
- the numeric removal conditions and due status
- `public_narrative.conditions.invalidation`
- the `public_id` of each linked decision (resolve through `public_decisions.source_key`)

Withdrawn or revoked decisions drop out of the view the same way they drop out of the feed.

**API** (`app/public/server.py`): add `GET /api/public/v2/portfolios/{portfolio_id}/shorts` →
`{ ...metadata, portfolio_id, status, items: [...open first, then removed newest first] }`.

**UI** (`public-ui/src`):
- add `'shorts'` to `TABS` in `App.tsx`
- add a `Shorts.tsx` modeled on `Positions.tsx`: summary row (ticker, days on the list, price change
  since declaration, removal-due badge); detail with declaration history, removal conditions,
  invalidation conditions, result, and "View decision trace →" links
- add types in `types.ts`, and extend `fixtures/generate.py` and `routes.mjs` with open, due and
  removed examples
- in `main.test.tsx`, test the tab renders, empty state, due badge and trace links
- copy says plainly that these are recommendations the account cannot take

## Maintainer decisions needed before building

1. Maximum `review_by` horizon (proposed: 60 calendar days).
2. May a due call be reaffirmed, and how many times (proposed: once, like re-underwriting)?
3. Should an intraday stop breach be detected from the review's quote, or only from completed-session
   closes (proposed: closes only, for determinism)?
4. Should paper short calls appear on the public dashboard (proposed: live only, matching the
   live-only UI)?

## Verification

- `python -m pytest -q`, `python -m ruff check .`, `python -m ruff format --check app tests`,
  `python -m mypy app tests`, and `npm test` in `public-ui`.
- Replay on a copy of `data/boustrategy.db`: inject an approved SHORT_WATCHLIST with conditions,
  then run `prepare` and confirm a `short_removal_due` trigger and a REMOVAL DUE intake line when the
  cached close crosses a condition.
- Worker test: a due call with no answer fails with the named shortfall after one retry; a
  removal or a valid re-underwrite passes.
- Publication on DB copies: `python -m app.public.publication --source <copy> --public-db <copy>`,
  then check `/shorts` output contains no private fields (assert against `refined_thesis` and
  `internal_notes` text).

## Deployment note

The public publisher (`boustrategy-public-publisher`) and server (`boustrategy-public-server`) are
long-running tasks. Restart both after deploying any schema or enum change, or they keep validating
with the old code.
