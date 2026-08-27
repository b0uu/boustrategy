# Plan 028: Reconcile doctrine and simplify the live execution foundation

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If a STOP condition occurs, stop and report instead of
> improvising. When done, update this plan's row in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat a15ba65..HEAD -- boustrategy_spec.md README.md DEVELOPMENT.md docs/reasoning/OPERATOR_GUIDE.md app/schemas/live_execution.py app/schemas/broker_execution.py app/broker/packet.py app/broker/config.py app/dashboard/queries.py app/dashboard/server.py app/storage/records.py ops/live.example.json tests`
> If an in-scope file changed, compare the current-state facts below with the
> live code. Stop on a material mismatch.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: bug, tech-debt, docs
- **Planned at**: commit `a15ba65`, 2026-08-27

## Why this matters

The current live profile treats $100 as a hard account-equity ceiling. That
contradicts the maintainer's decision that starting capital is flexible and
profits may accumulate. The new broker record also carries two unused or
duplicated presentation fields, and the private dashboard can offer an
execution prompt for an expired packet. Fix these small foundation problems
before adding dual-agent state.

This plan also makes the documentation honest: paper evaluation remains useful,
but it isn't a mandatory proof period before a deliberately small live pilot.
The localhost dashboard remains the personal operator/test surface. A separate
public showcase dashboard is a future product and is explicitly out of scope.

## Current state

- `boustrategy_spec.md:17` prescribes `Initial account capital: $500`, and
  section 3 also describes a live approximately-$500 account.
- `DEVELOPMENT.md`, under `Paper first, then proof`, says paper proof is a
  prerequisite for live trading.
- `docs/reasoning/OPERATOR_GUIDE.md` says each trial account is capped at $100
  of equity.
- `app/schemas/live_execution.py:21-30` defines `account_equity_cap` and
  constrains `max_order_notional` against it.
- `app/broker/packet.py:37-38` rejects `account_equity_cap_exceeded`.
- `app/schemas/broker_execution.py:29-36` stores typed
  `requested_notional`, free-form `notional_or_quantity`, and the constant
  `raw_broker_payload_private=True`. No raw payload is stored in this model.
- `app/dashboard/server.py:589` enables its copy button when any packet exists,
  without checking expiration or whether a broker execution already consumed
  it.
- Schema and policy must remain separate. Follow the explicit pydantic models
  in `app/schemas/` and plain pytest style in `tests/`.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Tests | `python -m pytest -q` | all tests pass |
| Lint | `python -m ruff check .` | exit 0 |
| Format | `python -m ruff format --check .` | exit 0 |
| Types | `python -m mypy app tests` | exit 0 |
| Diff hygiene | `git diff --check` | no output |

## Scope

**In scope**:

- `boustrategy_spec.md`
- `README.md`
- `DEVELOPMENT.md`
- `docs/reasoning/OPERATOR_GUIDE.md`
- `app/schemas/live_execution.py`
- `app/schemas/broker_execution.py`
- `app/broker/packet.py`
- `app/broker/config.py`
- `app/dashboard/queries.py`
- `app/dashboard/server.py`
- `app/storage/records.py`
- `ops/live.example.json`
- directly corresponding tests
- `plans/README.md` status only

**Out of scope**:

- `docs/mandate.md`, `docs/risk_policy.md`, and `docs/source_policy.md`
- public-dashboard design, hosting, authentication, or styling
- live portfolio snapshots or dual-agent reasoning attribution (plan 029)
- broker credentials, account activation, order review, or placement
- scheduling

## Git workflow

- Branch: `advisor/028-simplify-live-foundation`
- Use conventional commits such as `fix: simplify live execution foundation`.
- Do not push or open a PR unless explicitly instructed.

## Steps

### Step 1: Reconcile the written direction

Make these narrow documentation changes:

1. In `boustrategy_spec.md`, delete the `Initial account capital` field. In
   scope text, replace the approximately-$500 wording with `small dedicated
   Robinhood account`. Add one sentence near scope or operating principles:
   starting capital is deployment configuration and may differ by account; it
   is not strategy doctrine. Do not introduce a replacement dollar amount.
2. In `DEVELOPMENT.md`, replace the claim that paper proof is a prerequisite
   for live trading. Preserve paper trading as useful for replay, deterministic
   state testing, and lookahead-safe evaluation. State that small live pilots
   may run earlier to expose broker and operational behavior, with loss accepted
   inside the maintainer-approved risk framework.
3. In `README.md`, describe the localhost dashboard as the private personal
   operator panel and test surface. Add one short sentence that a separate
   public-facing dashboard will eventually present public-safe account
   performance and agent reasoning. Do not design that dashboard here.
4. In `docs/reasoning/OPERATOR_GUIDE.md`, remove the statement that account
   equity is capped at $100. Say the example profiles use a temporary per-order
   brake and flexible funded capital.
5. In `boustrategy_spec.md`'s broker execution record example, remove the two
   fields deleted in Step 3 below and use `requested_notional` as the single
   requested-size field.

**Verify**:

- `rg -n "Initial account capital|Live ~\$500|account_equity_cap|notional_or_quantity|raw_broker_payload_private" boustrategy_spec.md README.md DEVELOPMENT.md docs/reasoning/OPERATOR_GUIDE.md`
- Expected: no matches.

### Step 2: Remove the hard equity ceiling

1. Delete `account_equity_cap` from `ExecutionProfile`.
2. Rename `keep_order_cap_within_account_cap` to a validator whose only job is
   requiring a fingerprint for enabled profiles. Do not add a replacement
   capital field.
3. Delete `account_equity_cap_exceeded` from `build_execution_packet`.
4. Keep `account_equity` in preflight and packets because current equity is
   required to translate target weight into notional.
5. Keep `max_order_notional` as the temporary operational brake. It must be
   positive but need not be compared with a starting balance.
6. Remove the old field from public profile status and both example profiles.

Update tests to prove an enabled profile with account equity above its original
funding can still build a packet when target notional remains within
`max_order_notional` and buying power is sufficient.

**Verify**:

- `rg -n "account_equity_cap|account_equity_cap_exceeded" app ops tests`
- Expected: no matches.
- `python -m pytest -q tests/broker/test_packet.py tests/broker/test_run.py tests/dashboard/test_dashboard.py`
- Expected: all pass.

### Step 3: Remove redundant broker-record fields

1. Delete `notional_or_quantity` and `raw_broker_payload_private` from
   `BrokerExecutionRecord`.
2. Remove the now-unused `Literal` import.
3. Keep `requested_notional: float`; it is the single authoritative requested
   size and must continue matching the packet in `save_broker_execution_record`.
4. Update fixtures, CLI tests, lifecycle tests, storage tests, and schema tests.
5. Do not add a raw broker payload column. If raw payload archival becomes
   necessary later, it must be a private store designed explicitly for it.

**Verify**:

- `rg -n "notional_or_quantity|raw_broker_payload_private" app tests`
- Expected: no matches.
- `python -m pytest -q tests/schemas/test_broker_execution_schema.py tests/storage/test_records.py tests/broker`
- Expected: all pass.

### Step 4: Make execution readiness current and exact

Keep packet history visible, but change the execution-prompt readiness test so
the copy button is enabled only when at least one packet:

- belongs to an enabled execution profile;
- has `expires_at` strictly after the current UTC time; and
- has no `broker_execution_records` row for its order intent.

Prefer adding an `executed` boolean to the existing packet query and computing
readiness in `server.py`. Do not create a new service layer for one query. Add
dashboard tests for expired, executed, disabled-profile, and ready packets.

**Verify**:

- `python -m pytest -q tests/dashboard/test_dashboard.py`
- Expected: all pass, including the four readiness cases.

### Step 5: Run the complete gate and commit

Run all commands in the command table. Also run:

- `git status --short`
- Expected before commit: only in-scope files plus `plans/README.md`.
- `git diff --check`
- Expected: no output.

Commit with `fix: simplify live execution foundation`, then mark plan 028 DONE
with the commit hash and verification date.

## Test plan

- Profile schema accepts flexible equity because equity is no longer profile
  configuration.
- Packet succeeds above original funding and still rejects oversized orders,
  stale quotes, wrong accounts, wide spreads, and insufficient buying power.
- Broker record round-trip uses only typed `requested_notional`.
- Dashboard readiness rejects expired, already-executed, and disabled-profile
  packets.
- All existing paper behavior remains unchanged.

## Done criteria

- [ ] No fixed starting-capital amount remains in the spec.
- [ ] No `account_equity_cap` code or config remains.
- [ ] No redundant broker size/private flag remains.
- [ ] Execution prompt readiness requires a current unexecuted packet.
- [ ] Public dashboard work was not introduced.
- [ ] Full pytest, ruff, format, mypy, and diff checks pass.
- [ ] Plan 028 is marked DONE in `plans/README.md`.

## STOP conditions

Stop and report if:

- Removing the hard ceiling would also require changing a numeric rule in
  `docs/risk_policy.md` or `docs/risk_posture.md`.
- A real local config or account identifier appears in the diff.
- `requested_notional` is not sufficient to represent the currently supported
  Robinhood equity order-review call.
- The dashboard requires a new public mode to implement packet readiness.
- Any test attempts to connect to a real broker or the real database.

## Maintenance notes

Starting funding belongs in deployment records or account snapshots, not the
strategy spec. `max_order_notional` is an operational brake, not an assertion
about account size. Public-dashboard design remains deferred until after plan
030 and initial manual live operation.
