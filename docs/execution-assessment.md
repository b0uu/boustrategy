# Execution, scheduling and private-dashboard assessment

September 8, 2026, against the audited Plan 031 implementation and read-only host
inspection. The recommendation is to make the private dashboard the operator
interface to the existing persisted runtime, while keeping execution independent
of the browser. Do not start unattended live operation yet: the host lacks a
configured investment runtime, fresh account collection and demonstrated broker
reconciliation. An enabled account profile alone does not establish those capabilities.

The public dashboard remains read-only. This audit did not add private controls,
activate tasks, start models, publish real data or contact the broker.

## What is ready, and what is missing

The implementation has persisted logical runs and named attempts, account leases,
fencing, bounded model input/output, cancellation, explicit retry, immutable
schedule revisions, previews, eligible-session checks, prerequisite waits and
missed-window skips. Trusted submission binds current account/regime facts and
serializes quota evaluation with intent creation. Publication is a separate
process with atomic projection/checkpoint commits and bounded public reads.

The private dashboard currently provides paper preparation and prompt handoffs,
plus read views of actual runtime attempts. It does not offer the full runtime
control interface described below. The CLI is a one-shot worker, not an installed
service. The code can support deliberate operating trials; that is different from
having a running, authenticated, reconciled live system.

Read-only inspection found five disabled digester tasks, no investment-runtime
task, two decisions, one live snapshot captured September 4, and no broker
execution or paper-fill history. Runtime tables were absent in the source database.
The private profile file was not inspected: the previously supplied account
configuration remains the authority for its enabled state and chosen limits.
There is not enough actual reporting data to establish live returns or end-to-end
execution readiness.

## Recommended private controls

Use the same persisted records and trusted operations as the CLI. Avoid a second
scheduler in JavaScript or a dashboard-owned process that disappears when a tab closes.

| Control | Required behavior and current gap |
| --- | --- |
| Readiness | Show source freshness, digest/receipt completion, intake hash/size, eligible completed regime session, account/profile binding, snapshot age, active lease, schedule authority, collector health and publication lag separately. A green profile badge must not imply every prerequisite passed. Current runtime checks cover many submission prerequisites; the dashboard still needs this combined view. |
| Preview | Read the persisted schedule revision and calendar, showing intended due time, current eligibility, dependency state, grace window and expected next occurrence. Distinguish preview from an enabled host task. The readonly CLI preview already supplies a foundation. |
| Run now | Prepare current inputs and create a named manual run through the runtime. Show the account/mode, input timestamps and model before the operator starts it. Recheck readiness at start and submission. This is a deliberate model launch, not an extra per-trade approval requirement. |
| Pause | Persist a revision that prevents new claims. Say explicitly whether an existing attempt remains active. Current pause allows active work to finish; it is not an emergency order-cancellation control. |
| Named cancellation | Cancel a specific attempt with its current identity/fence. Stop authoring and expose whether any decisions/intents were already saved. Never describe reasoning cancellation as canceling an order already submitted to a broker. The CLI supports named-attempt cancellation. |
| Named retry | Show the failed attempt and its saved outputs, then explicitly create the next attempt under its logical run. The current CLI names the run; a dashboard should additionally verify that the displayed failed attempt is still the latest one. A completed/no-action run needs a new review, not retry. Never retry an uncertain broker submission as if nothing happened. |
| Diagnostics | Expose safe private error summaries, lease/heartbeat times, model identity, attempt history, dependency failures and bounded logs. Preserve the original failure and later successful retry. Treat raw prompts, paths, account identifiers and model logs as private. |
| Publication | Show last successful projection time, source observation time, current lag and last producer failure. Public timestamps must describe retained data truthfully. Start/restart the publisher under an explicit supervisor, independently of the browser and investment worker. |
| Broker reconciliation | Track packet, broker order ID, status, incremental fills, cancellations, fees, cash and settlement. Before any resend after timeout/crash, query the broker by durable identity and reconcile the ledger. The current code records trusted broker facts; it is not a complete automated collector or uncertain-order recovery service. |

A thin private interface has a maintenance and security cost, but it reduces
operator mistakes from copying IDs and interpreting several CLI outputs. The
persisted runtime is already the concurrency authority. Reusing it is preferable
to maintaining browser-local state or a second queue. Keep CLI access for recovery
when the UI or web process is unavailable.

## Scheduling cadence and fresh facts

Keep ingestion frequency separate from investment-review frequency. The existing
morning, midday, close and Sunday digester cadence supplies intake; it should not
automatically trigger a complete investment run after every digest.

Start operating trials with one routine review per eligible session after the
required digest and preparation receipt exist. A pre-open review can combine the
previous completed session's regime with current news, but execution must wait
for regular market hours and a fresh quote. An after-close review has completed
daily bars and can incorporate late news, but its proposal cannot be placed using
that night's expired account/quote facts. Neither schedule timing establishes an
investment edge. Choose one after measuring intake availability and review duration,
then add bounded event-driven reviews only when the research queue justifies them.

The current scheduler requires same-session completed intake. A pre-open path that
cannot meet that prerequisite needs deliberate preparation work, not a bypass.
Scheduled paper mode consumes a preparation receipt; live mode consumes a matching
prepared live run. The one-shot `scheduled` command must be invoked repeatedly
through the due/grace window, for example once per minute, by an explicitly
configured supervisor. `IgnoreNew` limits overlapping host invocations, and the
account lease independently handles overlap across callers. Record one skip after
a missed grace window rather than launching a backlog of historical reviews.

A trusted account collector is the main live dependency. Collect a new snapshot
before authoring and again when needed before submission. The existing five-minute
account-snapshot limit cannot cover an arbitrarily long authoring session. Keep
submission blocked until a fresh snapshot arrives. Recompute target-to-order sizing
from the current account and instrument position, then obtain a ticker-bound
preflight immediately before placement. Preserve no additional per-trade approval,
the $20 maximum notional, the 60-second quote age and the 50-bps spread ceiling.
Packet review/submission at expiry is rejected; an expired packet needs new facts
and a new packet, never an extended timestamp.

Watch process restarts, machine logout, clock/calendar coverage, stale scheduler
observations, missed prerequisites and collector failures. During a long one-shot
worker invocation, scheduler authority can become stale even while the attempt's
lease heartbeat remains fresh. Showing an unavailable countdown is correct.
A future independent host observer can report actual task state without launching
another investment attempt. Disabled-task NextRunTime values do not authorize work.

## Publication and accounting operations

Run the trusted publisher separately and observe its exit status and lag. Its
activity-only changes avoid full decision/accounting rebuilds, while checkpoint
version changes deliberately reconcile affected projections. Set a publication
service objective from measured source/publisher/browser delays, not from a
synthetic API latency result. A few seconds of publication polling can support
useful activity updates, but cannot compensate for a stale broker snapshot or a
failed collector. Alerts and any external notifications need separately configured
destinations and authorization.

Reporting collection must include cash, holdings, fees, funding, incremental fills
and corrections with stable identities. Exact linked returns need coverage and
valuations at external-flow boundaries. Broker account value snapshots alone do
not recreate those facts. Reconcile manual/external account activity too. Keep
paper results visibly simulated, preserve old fills, and do not compare the legacy
paper convention against adjusted-close total-return benchmarks as unqualified alpha.

Back up both databases. The source preserves decisions and account observations;
the public store also preserves opaque URL mappings and revocations. A projection
rebuild in the same public file preserves those identities. Restoring or replacing
an empty public file has different URL consequences. Follow the release runbook,
verify checksums and scope, and never copy a live WAL database file without its
required checkpoint/backup procedure.

## Authentication and research limits

Keep private controls on loopback until real authentication and restricted network
access are installed. A process CSRF token does not identify an operator. Remote
controls need authenticated sessions, authorization for mutations, CSRF protection,
origin/host validation and auditable named actions. Keep the public process unable
to reach broker credentials or private mutation routes. Consider a dedicated OS
account for unattended workers and collectors, with separate permissions for source
writes, publication and broker access. Read-only authoring sandboxing limits writes;
it does not establish confidentiality from every readable host file.

The supported authoring adapter receives a prepared intake. It is not a complete
autonomous outside-research collector. Maintain a bounded queue of unresolved
questions, catalysts, thesis conditions and independent sources. An X digest cannot
corroborate its own claims. Missing source evidence should be an explicit research
limitation, even when a model can technically return a valid no-action record.
Oversized intake fails as `intake_too_large` rather than silently dropping evidence.
Queue selection and richer research collection remain separate product work.

Track observed model identity, authoring duration, resource/subscription usage,
research coverage and useful/no-action outcomes. More scheduled sessions consume
capacity and increase stale-input exposure; they do not automatically improve
investment decisions. Avoid choosing autonomy from an uncalibrated confidence score.
This audit did not invoke a model or verify current subscription authentication.

## Staged activation recommendation

1. Keep the host inactive while reviewing this uncommitted delta. Establish backups,
   select the project environment, initialize trusted schema only as an explicit
   operating step, and verify publication on disposable fixtures.
2. Run deliberate supervised paper sessions with real prepared research. Review
   saved inputs, no-action outcomes, policy failures, new simulation-version fills,
   diagnostics and recovery. Supervision here observes the trial; it does not add
   a new policy requirement for approving each trade.
3. Activate only selected paper scheduling and publisher supervision. Observe several
   eligible sessions, a missing-input window, pause/cancel/retry and restart recovery.
   Measure missed windows, duplicate prevention, run duration, research sufficiency,
   publication lag and reconciliation errors before deciding whether coverage is adequate.
4. Implement and exercise fresh snapshot/preflight collection and durable broker
   reconciliation. Resolve uncertain submissions before any retry. Complete private
   authentication/isolation if remote controls are needed. Record who owns each
   operational failure and how the system stays blocked when facts are missing.
5. Deliberately select live activation with the existing execution settings. Verify
   actual account/fill/reporting facts after the first bounded live operation before
   expanding unattended scope. Keep a clear pause/reconciliation procedure and assess
   evidence before changing frequency, assets or numerical limits.

No stage has been activated by this audit. Remaining blockers are operational
capabilities and evidence, not a request to weaken policy or introduce per-trade
human approval. The recommended private controls should be a separate implementation
plan over the existing runtime after this release is reviewed.
