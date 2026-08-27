# Plan 029: Isolate controlled Codex/Claude reasoning and live portfolio state

> **Executor instructions**: Follow this plan exactly and verify every step.
> Stop on any STOP condition instead of inventing a workaround. Do not connect
> to Robinhood or place an order. When done, update this plan's row in
> `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat a15ba65..HEAD -- app/reason app/paper/context.py app/policy app/schemas app/state app/storage app/orders docs/reasoning docs/execution tests`
> Plan 028 is expected to have changed some listed files. Confirm plan 028 is
> marked DONE, then compare the current signatures below with live code. Stop
> on any other material drift.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: HIGH
- **Depends on**: plan 028
- **Category**: bug, migration, direction
- **Planned at**: commit `a15ba65`, 2026-08-27

## Why this matters

The intended trial is a controlled comparison: Codex and Claude receive the
same market/research intake, mandate, policy, and timing, but reason
independently and trade separate accounts. Today a live submit still builds
policy context from `paper_positions` and globally counts all order intents.
That can make one agent consume the other's quota and can approve a live trade
against a fictional $5,000 paper portfolio.

This plan introduces the minimum durable state needed for isolation: one
reasoning run per profile, one broker-sourced portfolio snapshot per profile,
and explicit links from every submitted live decision to its run. Paper mode
must remain unchanged.

## Current state

- `app/reason/run.py:149` always calls `app.paper.context.portfolio_context`,
  including for `execution_mode=LIVE`.
- `app/paper/context.py:42-45` counts all same-day order intents without an
  execution-profile filter.
- `InvestmentDecisionRecord` has no agent/run field. Keep investment doctrine
  out of execution routing; attribution belongs in a separate runtime record.
- `decision_records.decision_id` is a primary key and
  `order_intents.decision_id` is unique. Two runs must therefore author
  globally unique IDs.
- `build_intake` writes a paper portfolio into `bundle.md`. The live comparison
  needs one identical market/research bundle plus two separate account-state
  snapshots.
- Existing persistence uses pydantic JSON plus indexed scalar columns and
  additive SQLite migrations. Follow that pattern.

## Target state

For a date and slot, both profiles share the same immutable live intake file
and SHA-256 digest. Each profile has its own `ReasoningRun` and
`LivePortfolioSnapshot`. A live decision cannot be submitted without both,
and policy receives only that profile's positions, theme weights, and daily
quota counts.

### `ReasoningRun`

Create `app/schemas/reasoning_run.py` with:

- `reasoning_run_id`: non-empty; generated as
  `rr_<date>_<slot>_<execution_profile_id>`;
- `session_date`: date;
- `slot`: non-empty string;
- `execution_profile_id`: non-empty;
- `model_label`: non-empty free-form display label, not a provider enum;
- `shared_bundle_path`: non-empty;
- `shared_bundle_sha256`: exactly 64 lowercase hexadecimal characters;
- `portfolio_snapshot_id`: non-empty;
- `started_at`: aware datetime;
- `completed_at`: optional aware datetime;
- `result`: `PREPARED`, `NO_ACTION`, `DECISIONS_AUTHORED`, or `FAILED`;
- `decision_ids`: list of unique strings;
- `public_summary`: string.

Validation rules:

- `PREPARED` has no completion time or decision IDs.
- completed results require `completed_at` and a non-empty public summary;
- `NO_ACTION` requires no decision IDs;
- `DECISIONS_AUTHORED` requires at least one decision ID;
- IDs must be unique.

### `LivePortfolioSnapshot`

Add to `app/schemas/live_execution.py` or a focused sibling module:

- `portfolio_snapshot_id`;
- `execution_profile_id`;
- `broker_account_fingerprint`;
- `captured_at` aware datetime;
- `account_equity` positive;
- `buying_power` non-negative;
- `positions`: list of `{ticker, market_value, primary_theme_id}`.

Position tickers must use the existing ticker pattern, market value must be
non-negative, and primary theme may be empty only for no positions. Reject
duplicate tickers. The snapshot stores no credentials or raw broker payload.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Tests | `python -m pytest -q` | all pass |
| Lint | `python -m ruff check .` | exit 0 |
| Format | `python -m ruff format --check .` | exit 0 |
| Types | `python -m mypy app tests` | exit 0 |
| Diff | `git diff --check` | no output |

## Scope

**In scope**:

- `app/schemas/reasoning_run.py` (create)
- `app/schemas/live_execution.py`
- `app/reason/intake.py`
- `app/reason/run.py`
- `app/state/pipeline.py` only if needed to preserve explicit run linkage
- `app/paper/context.py` only for shared `PortfolioContext` construction
  primitives; paper behavior must not change
- `app/storage/database.py`
- `app/storage/records.py`
- `app/broker/run.py` for snapshot/run CLI boundaries
- `docs/reasoning/RUNBOOK.md`
- `docs/execution/EXECUTOR.md` only where exact IDs must be carried
- direct tests and fixtures
- `plans/README.md` status only

**Out of scope**:

- dashboard routes or styling (plan 030)
- public dashboard
- changing mandate, risk limits, source policy, or decision doctrine
- automatic scheduling
- broker credentials, transfers, review calls, or order placement
- merging the two agents' accounts, quotas, positions, or decisions
- model scoring or declaring a winner

## Git workflow

- Branch: `advisor/029-isolate-dual-agent-state`
- Commit message: `feat: isolate dual-agent live state`.
- Do not push or open a PR unless explicitly instructed.

## Steps

### Step 1: Add schemas and append-only stores

Create the two schemas above and these tables:

```sql
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
    PRIMARY KEY (reasoning_run_id, decision_id)
);
```

Implement explicit `save/get` functions. Saving identical content is
idempotent; conflicting content raises `ValueError`. A completed run is
append-only logically: expose a single transition function that changes
`PREPARED` to one terminal result and rejects further changes. Do not build a
generic repository abstraction.

Snapshot persistence must verify that its fingerprint and profile match an
enabled `ExecutionProfile` passed by the caller. Never persist the profile's
configured fingerprint in public dashboard data.

**Verify**:

- New schema tests cover all consistency rules.
- Storage tests cover idempotency, conflicting content, duplicate date/slot/
  profile, terminal transitions, and cross-profile rejection.
- `python -m pytest -q tests/schemas tests/storage`
- Expected: all pass.

### Step 2: Produce one shared live intake

Extend `build_intake` with an explicit mode or add one narrowly scoped live
entry point so it can write `shared_bundle.md` without the `Paper portfolio`
and paper quota sections. Regime, triggers, digests, article queue, calendar,
and required runtime reading must remain byte-identical for both profiles.

Compute SHA-256 from the final file bytes. A run stores this digest; it does
not store another copy of the bundle. Keep the existing paper `bundle.md` and
`portfolio.json` behavior unchanged.

Add a test that prepares Codex and Claude runs for the same date/slot and
asserts the exact same shared path and hash while snapshot IDs differ.

**Verify**:

- `python -m pytest -q tests/reason/test_reason.py`
- Expected: all pass; existing paper bundle assertions remain unchanged.

### Step 3: Build profile-specific live policy context

Implement a plain function, near the existing paper context code or in
`app/reason/live_context.py`, that returns the existing `PortfolioContext`
from a `LivePortfolioSnapshot`:

- `holdings_count`: number of non-zero positions;
- `primary_theme_weights`: each included position's market value divided by
  snapshot account equity, excluding the evaluated ticker;
- daily BUY and SELL counts: query only `LIVE` order intents whose
  `execution_profile_id` matches the snapshot profile and whose date matches;
- never read `paper_positions`, paper fills, or paper cash.

Reject a snapshot with total position value materially above account equity;
use a small documented floating-point tolerance only, not an arbitrary risk
buffer. Reject positions without a primary theme because concentration policy
cannot be enforced. Dedicated trial accounts are assumed to contain only
BouStrategy-created holdings; an unknown pre-existing holding is therefore a
fail-closed condition.

Tests must prove Codex orders do not consume Claude quotas and that different
position sets produce different theme weights from the same shared intake.

**Verify**:

- `python -m pytest -q tests/paper tests/reason tests/policy`
- Expected: all pass.

### Step 4: Require run and snapshot linkage for live submission

Change the live submit boundary, not the investment schema:

1. Paper submit remains backward-compatible and uses paper context.
2. Live submit requires `reasoning_run_id` and an enabled execution profile.
3. Load the run and its snapshot; require matching profile and account
   fingerprint.
4. Require the run to be `PREPARED` and the snapshot to be no older than five
   minutes at submission. Put this freshness value in one named constant.
5. Require each live `decision_id` to begin with
   `<reasoning_run_id>_`. This is the simple collision-proof namespace for the
   current primary-key design.
6. Evaluate policy with live context, create the intent for that profile, and
   atomically link the decision to the run. A failure must not leave a link
   without its decision/status trail.
7. Terminal run completion records either no action or its decision IDs and a
   public summary.

Use an explicit SQLite transaction at this multi-write boundary. Do not add a
generic unit-of-work framework.

Add CLI commands sufficient for agent sessions to save a validated snapshot,
prepare a run, submit against a run, and complete a run. JSON files are allowed
as the temporary agent bridge. Commands must print structured JSON and must not
echo account identifiers or fingerprints.

**Verify**:

- Tests cover missing run, stale snapshot, wrong profile, wrong decision-ID
  namespace, cross-account fingerprint, no-action completion, linked decision,
  idempotent retry, and rollback on failure.
- `python -m pytest -q tests/reason tests/state tests/broker tests/storage`
- Expected: all pass.

### Step 5: Tighten the runbooks

Update `docs/reasoning/RUNBOOK.md` so a live run:

- reads the shared bundle plus only its own snapshot;
- identifies its reasoning run and execution profile;
- never reads or acts on the other account;
- treats the paper portfolio as out of scope;
- submits every decision through the live run boundary;
- completes with a public summary even when result is no action.

Keep `docs/execution/EXECUTOR.md` execution-only. It receives only approved
intents/packets and must not become a second reasoning agent.

**Verify**:

- `rg -n "paper portfolio" docs/reasoning/RUNBOOK.md`
- Expected: any match explicitly says it is ignored/out of scope in live mode.
- Documentation tests, if present, pass.

### Step 6: Full verification and migration rehearsal

Run all commands in the command table. Copy `data/boustrategy.db` to a fresh
temporary directory, connect to the copy so migrations run, then verify:

- `PRAGMA integrity_check` returns `ok`;
- existing decision and intent counts are unchanged;
- the three new tables exist;
- no live snapshots or runs were inserted by migration.

Delete only the verified temporary directory. Never migrate or mutate the real
database during plan execution.

Commit and mark plan 029 DONE.

## Test plan

- Schema consistency and duplicate position handling.
- Append-only snapshot/run storage and terminal run transition.
- Identical shared intake hash for both profiles.
- Completely separate quotas, holdings, and theme weights.
- Paper submission regression coverage.
- Live submission profile/run/snapshot/fingerprint/freshness enforcement.
- Transaction rollback and idempotent retry.
- Migration rehearsal against a database copy.

## Done criteria

- [ ] Live policy never reads paper portfolio state.
- [ ] Codex and Claude share market/research input but not account state.
- [ ] Every live decision is linked to one reasoning run and profile.
- [ ] No-action runs are durable and attributable.
- [ ] Decision IDs cannot collide across runs.
- [ ] Paper workflow remains unchanged.
- [ ] No broker connection or public dashboard was added.
- [ ] Full verification passes and plan 029 is marked DONE.

## STOP conditions

Stop and report if:

- Plan 028 is not complete.
- Robinhood cannot provide all positions, equity, buying power, and a stable
  account identifier to the agent session.
- Existing dedicated accounts contain holdings that cannot be mapped to a
  BouStrategy decision/theme.
- Implementing isolation appears to require changing numeric risk doctrine.
- The only viable database design requires rewriting existing decision IDs or
  altering historical records.
- Any real credential or account identifier would enter git, logs, fixtures, or
  public output.

## Maintenance notes

The shared bundle hash is the experimental control. Account state is expected
to diverge and must not be forced equal after the first decision. Model labels
are descriptive metadata, not policy inputs. Public presentation is deferred;
plan 030 remains a private operator surface.
