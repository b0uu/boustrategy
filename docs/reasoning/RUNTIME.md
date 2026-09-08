# Private authoring runtime

The runtime turns a prepared intake into an actual, recorded authoring attempt.
It doesn't collect broker snapshots, fetch outside research, submit broker orders,
or install scheduled tasks. The Codex adapter receives the supplied evidence and
writes structured decisions through trusted schema and policy checks. Public HTTP
only reads the separate published database.

Manual mode is the default. The examples below configure an inactive paper
schedule. They don't change a live account or enable Windows tasks.

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

If you later activate a host task, invoke `scheduled` every minute through the
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
