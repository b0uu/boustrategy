# Private authoring runtime

The runtime turns a prepared intake into an actual, recorded authoring attempt.
It doesn't collect broker snapshots, fetch outside research, submit broker orders,
or install scheduled tasks. The Codex adapter receives the supplied evidence and
writes structured decisions through trusted schema and policy checks. Public HTTP
only reads the separate published database.

The examples below are safe manual/paper defaults for a new schedule. They don't
change a live account or enable Windows tasks. The deployed Agentic account uses
enabled live review schedules documented in [`ops/README.md`](../../ops/README.md).

## Retained manual and paper mode

The private dashboard is an operator and test surface bound to
`http://127.0.0.1:8378`; it may contain private operational data and must remain
localhost-only. Its Operate page retains the supervised paper workflow: confirm
a completed same-day digest, prepare the paper session, run a fresh reasoning
session from the recorded intake, and inspect decisions, policy outcomes and
paper fills. It does not schedule work, call a broker or place orders.

The deployed live path is separate. Scheduled review workers refresh broker
state before authoring and again before submission. The reasoning session has no
broker MCP. Approved, account-bound packets may pass to a separate
execution-only session governed by [`docs/execution/EXECUTOR.md`](../execution/EXECUTOR.md).
See [`ops/README.md`](../../ops/README.md) for the installed tasks, schedules and
recovery procedure.

## Configure and inspect without starting a model

From the repository root, use the same Python environment as the application:

```powershell
python -m app.reason.runtime --db data/boustrategy.db configure --in ops/runtime.schedule.example.json
python -m app.reason.runtime --db data/boustrategy.db preview --schedule paper-close
```

`preview` opens the existing source read-only and reports intended New York times,
including early closes. It doesn't claim that an installed task is enabled.
Each configuration is immutable and its revision must increment by one. The
example file is a first revision, so don't reapply an edited revision 1 after
initial configuration. Save a revision 2 with a new `configured_at` instead.
Live schedule configuration requires its account-bound execution profile. It may
remain inactive while that profile is disabled; actual execution requires the
profile to be enabled.

NYSE session coverage is January 1, 2026 through December 31, 2028. A previous
session before that range is unavailable. FOMC coverage is separate: 2026 and
tentative 2027 dates. Neither calendar invents future coverage. The existing
Sunday evening X digester remains independent of investment review sessions.

## Prepare and start a deliberate attempt

Preparation is a local file/database operation. It supplies the required strategy
and authoring documents, portfolio facts, approved source registry, current
observed holding episode IDs and prior evidence. It refuses an oversized intake
instead of silently dropping evidence. A missing episode history prevents
invented episode-bound thesis reviews. Conflicting latest review times are
reported without selecting a verdict.

A live intake also shows each holding's weight, quantity, average cost, price and
unrealized return from the starting snapshot, and derives holding episodes from
broker snapshots, because live activity coverage isn't recorded. It lists the
holdings due for a thesis review, with the reasons:

- On schedule: at 2% of equity or more, a holding is due at each review point
  (Monday 09:00, Wednesday 12:00 and Friday 12:00 ET, so the Monday morning,
  Wednesday midday and Friday midday reviews) until a review recorded after that
  point, or in the 24 hours before it, covers it. A missed point carries to the next review that runs.
- On a trigger since its last review: a daily price move of 5% or more, a volume
  spike, reported earnings, or its first close 15% under cost. Earnings dates come
  from the feed and from the review agent, which records every date it reads with
  its source; the agent's date outranks a feed estimate within 30 days of it.
- X headlines don't make a holding due on their own. The digester tags each
  significant post with every ticker it bears on, named or implied, and the intake
  lists the untriaged headlines tagged with a holding since its last review (at
  most 10). The review records an `x_triage` verdict for each: whether it could
  change that holding's thesis, with a one-line note. A thesis-changing verdict
  requires the holding's thesis review in the same output, and that review counts
  as trigger-driven.
- For three days after a trigger-driven review, neither the schedule nor another
  trigger makes the holding due, and no headline is listed for it.
- Regardless of the cooldown: its first close 40% under cost, or an invalidated
  verdict with no sale since.

When buying power is below the 5% minimum initial position, cash can't fund a new
holding, and the intake says so. Every candidate the review marks `clears_entry_bar`
that isn't held then needs a `challenger_reviews` entry: the holding the agent judges
weakest, why, and a verdict of `swap` or `keep_incumbent`. That holding must be
reviewed in the same output as a fresh buy at today's price. A swap needs a SELL or
TRIM of the holding and a BUY of the candidate, with the sale plus cash on hand
freeing at least the buy's target weight; a kept-out candidate can't also be bought.
Nothing arms while the market is closed, since neither leg could trade. Sales are
submitted before buys. A swap BUY is recorded in `swap_pairs` with its sale, sits
outside the ordinary 2/day BUY/ADD limit (the 5/day breaker still counts it), and the
executor sends it only after its sale fills (`awaiting_swap_sale`), never after a
failed one (`swap_sell_failed`). If a review is accepted without its buys, a sale that
only funded one is held back too, unless that holding was judged invalidated.

Every BUY or ADD, and every thesis review, states where the thesis ends:
`realization_price_low` (fully priced in), `realization_price_high` (overpriced) and
`invalidation_price`. A holding's current range is its latest statement, from a review
or a BUY or ADD. Raising the range or lowering the invalidation price needs
`range_change_evidence`; raises aren't capped, and every statement is kept. A holding's
first close at or above its fully priced price is a trigger (`realization_reached`).
Trading at or above its overpriced price (`above_realization_range`) or at or below its
invalidation price (`below_invalidation_price`) is mandatory, whatever the cooldown,
until a sale goes through or a review moves the range past the price with evidence; a
review that leaves the price beyond the range while the market is open needs a SELL or
TRIM. The intake shows each holding's upside to fully priced, downside to invalidation
and their ratio, and the public positions panel shows the range and upside.

Preparation tracks prices, earnings and triggers for live holdings whether or not
the watchlist names them. The agent's verdict is binary: `intact` (it would still
own the holding at today's price) or `invalidated`. An invalidated holding needs a
SELL or TRIM in the first review that can trade. The worker sends back an output
that leaves a due holding without a review carrying a summary and an opened source
URL. Holdings don't count toward the hunt's three researched candidates, and the
session must open at least three pages plus one per thesis review it returns. If the retry still leaves one unanswered, the output is accepted without its
BUY and ADD records, and the holding stays due. Each saved review records why it was
due, and the public positions panel shows the latest approved review.

For a paper intake you've already prepared:

```powershell
python -m app.reason.runtime --db data/boustrategy.db prepare --intake data/intake.md --out data/runtime-intakes --run-id paper-review-example
```

For an existing live `PREPARED` reasoning run, use `--reasoning-run` instead of
`--intake`. The wrapper must match its account, session, slot and immutable bundle
hash. A legacy reasoning run and a scheduled occurrence can each have only one
runtime wrapper.

The following command starts a paid model. Run it only when you're ready to
execute the named prepared intake and have supplied a supported model ID:

```powershell
python -m app.reason.runtime --db data/boustrategy.db start --run paper-review-example --model YOUR_MODEL_ID --logs data/runtime-logs --timeout 1800
```

The adapter uses `codex exec` with stdin, JSON events, a strict output schema,
read-only sandbox, ignored user configuration and an explicit model. It runs in a
fresh temporary directory and passes only the operating-system and Codex
authentication environment it needs. Broker and X credentials aren't inherited.
The executable must be on PATH. No real model invocation is part of automated
verification.

The subprocess has bounded input, event logs and final output. Cancellation and
timeout stop its process tree. Windows uses a kill-on-close Job Object, including
inherited pipes and abrupt parent exit. POSIX process-group cleanup covers
controlled shutdown; an abrupt SIGKILL of the parent can leave children behind. Logs and diagnostic tracebacks stay under the private logs folder.
The public site receives only safe outcome codes, approved summaries, recorded
coarse stages and actual timestamps. Requested model identity isn't presented as
an observed provider version. There's no fabricated token or reasoning progress.

Live readiness is checked before authoring and again at trusted submission. The
account snapshot must meet the existing five-minute freshness requirement, and
regime data must belong to the most recent completed NYSE session and have been
computed after that session's close. A fresh snapshot collector is still needed
if a long attempt outlives the original snapshot. The runtime never extends the
freshness limit to make a run pass. Submitted intents are serialized with quota
checks in one SQLite write transaction and bound to the run's New York date.

## Stop, reconcile and explicitly retry

```powershell
python -m app.reason.runtime --db data/boustrategy.db cancel --attempt ACTUAL_ATTEMPT_ID
python -m app.reason.runtime --db data/boustrategy.db reconcile
python -m app.reason.runtime --db data/boustrategy.db retry --run paper-review-example --model YOUR_MODEL_ID --logs data/runtime-logs
```

Cancel names an actual attempt. It doesn't cancel orders already submitted to a
broker. Expired leases fence out late submission and completion. Reconciliation
marks lost attempts expired without rerunning them. Retry creates a new attempt
under the same logical run, preserves saved decisions and earlier outcomes, and
uses a new decision namespace with the actual retry model. A completed/no-action
run can't be retried. A new day's review needs a new prepared run. Never use
reasoning retry to resend an uncertain broker order.

## Scheduled execution and truthful countdowns

An enabled `scheduled` revision permits the private scheduled command to claim
eligible occurrences. Enabling the revision is a deliberate operating change,
separate from these inactive examples. An external process/task must actually
invoke the command; this CLI doesn't install one.

```powershell
python -m app.reason.runtime --db data/boustrategy.db scheduled --schedule paper-close --model YOUR_MODEL_ID --paper-preparation data/preparation.json --digest-dir data/digests --out data/runtime-intakes --logs data/runtime-logs
python -m app.reason.runtime --db data/boustrategy.db pause --schedule paper-close
python -m app.reason.runtime --db data/boustrategy.db resume --schedule paper-close
```

`--paper-preparation` is the JSON receipt from `app.reason.run prepare`, not a
raw markdown bundle. A scheduled live review consumes its matching same-session,
same-slot prepared live intake. Both require a completed same-day digest. Missing
prerequisites remain waiting during the grace window, with private diagnostics.
After grace they become skipped. Overlapping account work doesn't create another
active attempt. A worker restart reuses a prepared occurrence; it doesn't invent
a new run or automatically retry a prior failed attempt.

Pause prevents new claims while allowing an active attempt to finish. Resume
clears pause but doesn't enable a disabled schedule or install a task. Each
operation records a new revision. Editing a waiting occurrence updates its due
time while preserving occurrence identity. Claimed occurrences aren't replayed
because a schedule was edited.

When adding or operating a host task, invoke `scheduled` every minute through the
due/grace window, not just once a day. A single invocation with a missing digest
leaves the occurrence waiting until another invocation checks it. Configure the
host task to ignore a new invocation while its previous process is still running
(`IgnoreNew` in Windows Task Scheduler). The database account lease independently
prevents overlapping work from another task or manual command. During a long
authoring invocation, worker lease heartbeats continue but scheduler observation
can become stale, which truthfully suppresses a future countdown. No recurring
task is installed or enabled by this example.

The scheduled command records that a worker actually ran. Its observation expires
by the configured age, so one successful invocation doesn't promise an ongoing
scheduler. A trusted external observer may submit `SchedulerObservation` JSON:

```powershell
python -m app.reason.runtime --db data/boustrategy.db observe --in data/scheduler-observation.json
python -m app.reason.runtime --db data/boustrategy.db due --schedule paper-close
```

An observation names `schedule_id`, `revision`, aware `observed_at`, `observer`
(`worker` or `windows_task`), `configured`, `enabled`, and optional `next_run_at`.
Only report actual state. A disabled Windows task with a future NextRunTime is
still disabled. The public countdown needs an enabled configured schedule and a
fresh matching observation. Missing, stale, paused, disabled and out-of-coverage
states suppress the countdown. `due` records occurrences but doesn't start a
model. GET requests never observe Task Scheduler or enqueue work.

## Publish and recover

```powershell
python -m app.public.publication --source data/boustrategy.db --public-db data/boustrategy.public.db
python -m app.public.publication --source data/boustrategy.db --public-db data/boustrategy.public.db --watch 2
```

Add `--live-profile` for each deliberately included profile and
`--live-account-id` for its reporting account when publishing live history. Those
identifiers are private producer inputs. Keep the source and public paths distinct.
Watch requires an existing source database, initializes trusted change tracking
and WAL there, and polls at the selected interval. Public GET never initializes
the source or public store and never writes SQLite sidecars.

A publication transaction commits projections and its checkpoint together. A crash
retries the same dirty work. Heartbeats update only changed activity; one changed
decision doesn't deserialize the whole history. Corrections requiring broader
projection rebuilds, source replacement/counter regression and profile changes
are reconciled. Day/completed-session transitions refresh accounting eligibility
without replaying immutable decision traces. Source WAL permits worker heartbeats
while a large initial publication reads a consistent source snapshot.

Use `--rebuild` to reconstruct projections while retaining the existing public ID
mapping and revocations. Back up the public database too. Rebuilding into a new,
empty public database loses legacy decision ID mappings and changes their URLs.
Watch isn't a service installer. Keep it under a deliberate process supervisor if
you need continuous publication, and monitor its exit status and publication lag.

Wrapping a previously published manual run retains its public logical-run ID.
Its existing activity and decision links continue to resolve as attempts are added.

Use [`docs/public-release.md`](../public-release.md) for the complete public release gates, synthetic
HTTP benchmark, built-browser checks, read-only smoke, and public-store recovery procedure.

The public API provides scoped `/runtime`, paginated `/activity`, and
`/activity/{public_id}` under `/api/public/v2/portfolios/{portfolio_id}`. Activity
detail retains up to the latest 100 attempt summaries and explicitly reports
truncation and total count. Private source history retains all attempts. Decision
feed `run_id` filters use the opaque public run ID. No-action and skipped sessions
have activity records without fabricated ticker decisions.
