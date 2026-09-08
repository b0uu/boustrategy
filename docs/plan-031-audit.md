# Plan 031 audit and focused refactor

Completed September 8, 2026 in the uncommitted main tree, after Phases 1 through 6.
The audit used the executor brief and review notes as hypotheses, checked current
code, and applied sequential batches with focused tests. The executor checkout
remains the earlier phase baseline; audit changes are in main. No commit, push,
deployment, model invocation, broker call, task activation or source database write
was performed. The private live configuration was not opened, copied or changed.

## Reviewed areas and disposition

| Area | Findings and changes |
| --- | --- |
| Execution and schemas | Packet creation binds preflight ticker, decision ID/ticker, actionable side and final target. Packet storage independently binds the persisted decision and intent, including order type. Empty legacy preflight tickers remain parseable but cannot create packets. Existing packet reads remain supported. Live economic models reject NaN/infinity; bars require positive finite OHLC/adjusted prices and nonnegative volume. Zero-volume averages skip the spike trigger. |
| Broker lifecycle | New stored timestamps are UTC; legacy timestamp ordering compares instants. Review and submission cannot precede packet creation or occur at/after expiry. Review-only cancellation can occur without an order, including after quote expiry. A lifecycle keeps one intent/profile/packet identity. An immediate transaction serializes validation and insertion; concurrent terminal-event tests permit exactly one winner. |
| Decision processing | Replays cannot change intent or recorded evaluation mode/profile. Same-scope idempotency remains. Live quota evaluation already ran inside an immediate transaction, and live submission already bound the New York session, fresh snapshot and last completed regime session. Those protections were retained. |
| Regime and calendar | Historical snapshot replay now derives its predecessor from earlier dates only. Inserting new history before future snapshots fails explicitly rather than silently changing hysteresis. Completed-session intake and live-regime prerequisites were already implemented. Replay studies now count eligible exchange sessions, require exact endpoint bars and exclude an unfinished same-day close. |
| Paper simulation | New `next_open_v2` fills size existing holdings at contemporaneous opens. Missing required opens wait; buys exceeding cash fail without resizing. Settlement and rebuild are atomic. Live/unscoped or instrument-mismatched fills block paper balances, settlement and rebuild. Existing fills remain unchanged with additive `legacy_close_v1` metadata. Backdated settlement before existing fill history is refused. |
| Resource lifetimes | Private servers initialize outside GET and close request connections. Paper preparation runs in a threadpool with its connection created and closed there. Broker, paper, regime, newsletter, trigger and X CLIs now close on success and failure. Database initialization closes its connection if initialization fails. Existing public readonly connection lifetimes and runtime CLI cleanup were retained. |
| Private read correctness | Historical paper charts use shared paper observations instead of repeated per-date replay. Missing private quotes no longer become zero-valued holdings. The live operator displays actual attempt status/history and disables the manual prompt handoff for runtime-owned work. This adds read correctness, not a control plane. |
| Labeling | Script-delimiting predictor characters and dynamic HTML attributes are escaped. Links/media permit HTTP(S) schemes. Thread mutations validate all members against the anchor's author/conversation and commit together, including signal capture. SQLite connection annotations replace `Any`. Adjudication documentation now accurately describes replacement of the current verdict while retaining the original label. |
| Newsletters | Source components reject traversal/reserved names and archive destinations stay within the archive. A duplicate is removed only after matching archived content is confirmed or restored. New content is copied and recorded before inbox removal, preserving a recoverable copy across file/database failure. Annotation conflicts are checked before batch insertion. |
| X and experiments | Negative budget updates fail. Fetching retains the original since/start window and opaque pagination token across bounded calls and failures. Existing spending limits remain. Exporters refuse a directory containing earlier generated batches instead of letting stale batches be consumed or deleting user files. Prediction ingestion validates all rows before insertion. Excluded predictions no longer inflate missing-label counts. Watchlist suggestions preserve approved entries and notes. |
| Reporting and publication | Decimal schema checks use local precision compatible with declared bounds. Reused flow boundaries and gaps between simultaneous flow boundaries suppress returns. Prior-positive zero balances are distinguished from unfunded accounts. Legacy paper benchmark comparisons are withheld for incompatible corporate-action conventions. Account identity is checked once before materialization, and only boundary valuations are rescanned by linked-return calls. Publication checkpoint version 7 forces existing projections to refresh after these changes. |
| Public frontend/API | Existing bounded queries, cursor/retraction handling, sanitization, mode isolation and the six-phase release matrix were retained. The zero-balance position message recognizes the new state. Live remains default, paper stays separate, and Agent dashboard remains the sole top navigation label. |
| Operations/dependencies | The task installer registers disabled definitions unless `-Enable` is selected explicitly. No installer was run. The half-day comment now identifies Thanksgiving Friday correctly. Narrow runtime floors exclude the previously observed affected idna, requests and urllib3 versions. A separate audit venv was used; global packages were not upgraded. |

## Verification

Focused batches covered broker/schema/price/trigger/regime/state/live submission,
paper/reporting/reasoning, private dashboard, newsletters/labeling and X replay.
Regression tests exercise mismatched approved targets and actions, unbound quotes,
non-finite inputs, zero-volume averages, concurrent terminal events, timezone offsets,
pre-creation review, unaffordable paper buys, missing opens, rebuild rollback,
contamination, thread membership, script escape, archive recovery, pagination retry,
watchlist preservation, historical regime replay and flow-boundary reuse.

Final gates passed: 506 Python tests in the isolated environment, 26 React tests,
Ruff lint and full format check, strict mypy over 160 files, TypeScript, ESLint,
production build and `git diff --check`. Two upstream deprecation warnings from
Starlette/httpx/AnyIO remain; they did not fail tests. The newer Ruff formatter's
Markdown discovery is explicitly excluded in project configuration, keeping
historical plan examples and protected prompts outside source formatting.
PowerShell parsed the edited task installer without errors; it was not executed.

The final 100,000-record HTTP benchmark used 20 clients and 100 requests per route.
Feed p50/p95 was 293.602/370.728 ms; overview was 57.069/71.770 ms. Feed/overview used
seven/four direct SQL statements, returned bounded payloads and left the database
checksum unchanged without WAL/SHM files. See `docs/public-release.md` for the release
procedure. Policy parity remained 26,460 cases
with digest `759dba0432a0e1131a1de0b70b1db8b8af645ac27203ab76f2b3c64633766b4f`.
Comparison against the phase executor baseline found no changes to the policy
evaluator, strategy documents or prompt files. The pre-existing prompt edit in
main was preserved as part of that baseline.

A synthetic flat-account producer workload measured 500/1,000/2,000 chart points
at 0.268/1.393/4.036 seconds before removing repeated account validation, and
0.051/0.081/0.152 seconds afterward. These are repeated same-day chart points to
isolate producer cost, not valid multi-year daily market observations. Existing
HTTP benchmarks separately measure the public read path. Flow-heavy accounting
still scans relevant flows per point; this refactor does not claim linear scaling
for every possible reporting history.

## Dependency evidence

The checked venv used Python 3.14.2, Pydantic 2.13.5, yfinance 1.7.0, FastAPI 0.141.1,
Starlette 1.6.0, httpx 0.28.1, Uvicorn 0.52.4, idna 3.19, requests 2.34.2 and urllib3
2.7.0. `pip check` passed. npm audit reported zero known vulnerabilities across
315 dependencies. PyPI advisory metadata was checked for all installed venv
packages. That check also found the venv bootstrap pip 25.3 affected; only the venv
installer was upgraded to pip 26.2.1. Rechecking all 50 installed packages found no
listed advisories at their installed versions. This is an advisory/version check, not evidence
of an application exploit or a guarantee that dependencies contain no defects.

The runtime floors are `idna>=3.15`, `requests>=2.33.0`, and `urllib3>=2.7.0`.
Upstream evidence: [idna advisory](https://github.com/kjd/idna/security/advisories/GHSA-65pc-fj4g-8rjx),
[requests advisory](https://github.com/psf/requests/security/advisories/GHSA-gc5v-m9x4-r6x2),
and [urllib3 advisory](https://github.com/urllib3/urllib3/security/advisories/GHSA-mf9v-mfxr-j63j).
The requests issue concerns `extract_zipped_paths`, not ordinary request handling.
X continuation follows the [documented pagination contract](https://docs.x.com/x-api/fundamentals/pagination).
Use a current installer in an isolated environment when preparing deployment;
this audit did not migrate the package manager or introduce a lockfile.

## Retained choices and limits

- The schema/policy boundary, numerical investment rules, no extra trade approval,
  $20 notional brake, 60-second quote age and 50-bps spread ceiling are unchanged.
  A bound preflight is still a trusted operator/broker fact, not cryptographic
  proof that a quote came from a broker.
- Existing small modules, explicit SQL and transaction/network exception boundaries
  were retained. No repository/service framework, generic cache, new private
  control plane or additional public page was introduced.
- New paper fills use the next cached opening bar. Missing first-session bars can
  still delay that simulation's entry; the stricter exact-session horizon applies
  to the separately labeled replay study. Existing paper quantities are floats,
  and the simulator does not model corporate actions, fees or slippage. No automatic
  late-intent resimulation or destructive ledger cleanup was attempted.
- Export reruns need a fresh output directory if generated batches already exist.
  Pagination tokens can expire upstream; an expired token fails without advancing
  the checkpoint. An operator must resolve that preserved window explicitly.
- Private dashboards remain loopback tools without remote user authentication.
  The existing CSRF token is not authentication. Authenticated remote control and
  credential isolation are future activation work.
- Real account reconciliation, complete live return history, model quality,
  subscription authentication, outside-research completeness and unattended restart
  behavior on the actual account were not proven by synthetic tests. No real
  publication was run. This is a scoped code audit and regression pass, not a formal
  penetration test, exhaustive verification or profitability validation.

Read-only host inspection found two decisions, one September 4 live snapshot, no
live reasoning/execution records and no paper fills. Runtime tables were absent
from the source, so code integration has not initialized that production schema.
The source checksum remained unchanged. All five installed digester tasks were
Disabled, and no investment-runtime task was listed. Account enablement described
in the handoff was not re-read from the protected private configuration.
