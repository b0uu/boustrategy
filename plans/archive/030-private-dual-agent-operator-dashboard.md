# Plan 030: Add the dual-agent live workflow to the private operator dashboard

> **Executor instructions**: Follow this plan exactly. Run every verification
> command. Stop on a STOP condition instead of expanding scope. This is the
> private localhost operator panel, not the public showcase dashboard. When
> done, update this plan's row in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat a15ba65..HEAD -- app/dashboard app/reason app/broker app/schemas app/storage docs/reasoning tests/dashboard start-boustrategy.cmd`
> Plans 028 and 029 are expected to have changed these paths. Confirm both are
> DONE and compare the current state below with live code before continuing.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans 028 and 029
- **Category**: direction, dx
- **Planned at**: commit `a15ba65`, 2026-08-27

## Why this matters

The maintainer prefers a simple interface over memorizing commands. The private
dashboard should act as a personal control panel and test surface for one
Codex profile and one Claude profile. It should make the controlled comparison,
readiness gates, failures, and exact next prompt visible without becoming a
broker order-entry form or a second state engine.

The separate public dashboard is intentionally deferred. Do not design it,
choose a frontend stack for it, or expose private data in anticipation of it.

## Current state

- `app/dashboard/server.py` is a single FastAPI server rendered with inline
  HTML/CSS, bound to `127.0.0.1` by `main()`.
- `/operate` guides one paper cycle and has one state-changing preparation POST
  protected by a CSRF token.
- `/executions` shows profiles, packets, records, lifecycle events, and one
  generic execution prompt. It never places an order.
- Plans 028 and 029 will provide exact packet readiness, reasoning runs,
  profile-specific snapshots, and shared bundle hashes. The dashboard must
  query those stores rather than reimplementing their business rules.
- Follow the existing `queries.py` plain-function and `server.py` rendering
  split. Do not add React, a template engine, a CSS framework, a build step, or
  client-side application state.

## Target operator flow

The private dashboard exposes two explicit modes:

1. **Paper**: the existing workflow remains available and behavior-compatible.
2. **Dual-agent live trial**: one shared intake with two profile cards. Each
   card shows only that profile's snapshot, run, decisions, packets, execution
   state, and copyable prompts.

The live page guides this sequence:

1. complete the same-day digest;
2. prepare the shared market/research bundle once;
3. copy one profile-specific reasoning prompt for Codex and one for Claude;
4. inspect each run's result, including no action;
5. copy an execution-only prompt only for a current unexecuted packet;
6. inspect broker lifecycle reconciliation.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Dashboard tests | `python -m pytest -q tests/dashboard` | all pass |
| Full tests | `python -m pytest -q` | all pass |
| Lint | `python -m ruff check .` | exit 0 |
| Format | `python -m ruff format --check .` | exit 0 |
| Types | `python -m mypy app tests` | exit 0 |
| Diff | `git diff --check` | no output |

## Scope

**In scope**:

- `app/dashboard/queries.py`
- `app/dashboard/server.py`
- `tests/dashboard/`
- `docs/reasoning/OPERATOR_GUIDE.md`
- `README.md` only if launcher navigation needs one corrected sentence
- `start-boustrategy.cmd` only if the existing launcher cannot reach the new
  private route
- `plans/README.md` status only

**Out of scope**:

- a public dashboard, public mode, hosting, domains, authentication, SEO, or a
  public API
- direct Robinhood calls or order placement from FastAPI
- automatic agent-session launching
- scheduling
- changes to schemas, policy, packet construction, or persistence contracts
  delivered by plans 028/029
- a frontend framework, template engine, WebSocket, or polling architecture

## Git workflow

- Branch: `advisor/030-private-dual-agent-dashboard`
- Commit message: `feat: add dual-agent live operator workflow`.
- Do not push or open a PR unless explicitly instructed.

## Steps

### Step 1: Add read-only dual-agent query projections

Add plain query functions that return:

- shared bundle path/hash/date/slot;
- one row per configured profile with account-bound/enabled state;
- latest portfolio snapshot timestamp, equity, buying power, and positions;
- latest reasoning run result, public summary, and decision count;
- pending current packet count;
- latest execution status and error detail.

The query layer may join durable tables but must not decide policy, refresh
quotes, create packets, or transition state. Return only the fields needed by
the private page. Do not return broker fingerprints or raw JSON blobs.

Tests must cover an empty database, one ready profile, two diverged profiles,
no-action, decisions authored, stale snapshot, expired packet, and failed
execution.

**Verify**:

- `python -m pytest -q tests/dashboard -k "query or dual or live"`
- Expected: all selected tests pass.

### Step 2: Add a dedicated private live-operator route

Add `/operate/live` and leave `/operate` as paper. Update navigation labels so
the distinction is obvious:

- `Paper operator`
- `Live trial`
- `Executions`

The live page should use the existing visual language and consist of:

- one compact shared-intake readiness panel;
- two profile cards in a responsive grid;
- a short comparison table below the cards;
- clear warning/error text from durable state;
- exact next-action text.

Each profile card must show:

- display label and execution profile ID;
- enabled/account-bound readiness without revealing the fingerprint;
- latest snapshot age, equity, buying power, and position count;
- reasoning run status and public summary;
- decision count;
- pending packet and broker status;
- a profile-specific reasoning prompt;
- a profile-specific execution prompt when eligible.

Keep CSS additions small and within the existing stylesheet. Do not redesign
unrelated pages.

**Verify**:

- TestClient smoke tests return 200 for `/operate`, `/operate/live`, and
  `/executions` on empty and populated synthetic databases.
- Escaping tests prove summaries, ticker text, and error details cannot inject
  HTML.

### Step 3: Generate exact profile-specific prompts

Reasoning prompt requirements:

- identify the exact reasoning run and profile;
- cite the shared bundle path and hash;
- cite only that profile's snapshot ID;
- state that market/research inputs match the other agent but account state is
  intentionally isolated;
- require `docs/reasoning/RUNBOOK.md`;
- require terminal completion with a public summary, including no action;
- forbid reading or acting on the other profile.

Execution prompt requirements:

- identify one exact packet ID and profile;
- require `docs/execution/EXECUTOR.md`;
- remain disabled unless the profile is enabled/account-bound and the packet
  is current, unexecuted, and belongs to that profile;
- stop after one reconciled packet;
- never include a fingerprint, account identifier, credential, or raw broker
  payload.

Prompt rendering must be a small pure function or explicit inline block in
`server.py`; do not introduce a prompt framework.

**Verify**:

- Tests assert exact run/profile/snapshot/packet identifiers appear.
- Tests assert the other profile's snapshot and packet IDs do not appear in a
  profile prompt.
- Tests assert buttons remain disabled for every failed readiness condition.

### Step 4: Keep state-changing actions narrow

If shared live intake preparation needs a POST endpoint, it may call only the
existing deterministic preparation service added by plan 029. It must:

- remain CSRF-protected;
- reject future dates;
- require a ready same-day digest;
- create no broker snapshot, decision, packet, execution record, or order;
- redirect back to `/operate/live` with a concise result.

Do not add buttons that claim to launch Codex, Claude, Robinhood review, or
placement. The current product copies prompts into manually started sessions.

**Verify**:

- Route-table test identifies every POST endpoint and confirms each is local
  preparation only.
- CSRF and future-date rejection tests pass.

### Step 5: Update the operator guide

Document the two private modes in `docs/reasoning/OPERATOR_GUIDE.md`. Explain
in plain language:

- the localhost dashboard is personal and may show private operational data;
- the two agents share research inputs but not account state;
- the dashboard copies prompts rather than launching agents;
- it never places an order;
- scheduling is still deferred;
- the eventual public dashboard is separate and intentionally not part of this
  implementation.

Do not write public-dashboard requirements beyond that boundary statement.

### Step 6: Full verification and handoff

Run all commands in the command table. Manually launch the dashboard against a
temporary synthetic database only, confirm the three operator/execution pages
load on `127.0.0.1`, then stop the process. Do not use the real database for
the manual smoke test.

Commit and mark plan 030 DONE.

## Test plan

- Query projections: empty, one profile, two diverged profiles.
- Private page rendering and HTML escaping.
- Shared bundle and profile-specific prompt isolation.
- No-action and authored-decision states.
- Stale snapshot, expired packet, disabled profile, and failed execution.
- Exact route mutation allowlist and CSRF behavior.
- Existing paper operator regression tests.

## Done criteria

- [ ] Paper and live trial modes are clearly separate.
- [ ] Codex and Claude cards show isolated state and the same shared bundle.
- [ ] Prompts contain exact safe identifiers and no account secrets.
- [ ] No stale or executed packet can enable an execution prompt.
- [ ] The FastAPI app still cannot place broker orders.
- [ ] No public-dashboard implementation was added.
- [ ] Full verification passes and plan 030 is marked DONE.

## STOP conditions

Stop and report if:

- Plans 028 or 029 are incomplete or their schemas differ materially.
- Rendering the required state needs direct broker access from FastAPI.
- A proposed route would expose the server beyond `127.0.0.1`.
- A change would place an order, launch an agent automatically, or schedule a
  task.
- The implementation starts creating a second public mode or duplicating
  policy/readiness logic in the UI.
- Any real account identifier, fingerprint, credential, or private payload
  would appear in HTML, tests, screenshots, or git.

## Maintenance notes

This private dashboard may continue growing as a personal test suite, but it
must remain operationally honest and localhost-only. The future public
dashboard should be a separate, public-safe projection centered on performance
and agent reasoning; it should not be built by exposing or restyling these
private pages.
