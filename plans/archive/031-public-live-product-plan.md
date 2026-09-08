# Plan 031: Complete the public live-agent product

## Status and product direction

- Planned September 5, 2026, against HEAD `40b317b` plus the uncommitted public UI/backend work inspected during this review.
- Priority P1; large, phased scope. Status: COMPLETE in the uncommitted main tree; operational activation remains deferred. The maintainer approved execution on September 5, 2026. Additional pages are bookmarked for later; scheduling activation and numerical policy changes remain separate operating choices.
- User decision: live portfolios are primary; paper results remain clearly separate.
- User clarification: one live account is available now. The earlier Codex/Claude dual-account design isn't the current deployment model. Build one BouStrategy experience with modular portfolio and agent identity; no two-agent selector or comparison page in this release.
- If the model changes on the same account, preserve one portfolio history and annotate model/version periods. Don't pretend sequential model periods were independent accounts or a controlled comparison.
- Existing specs describe current choices, not unquestionable product requirements. This plan reevaluates them. The initial planning review changed no application code, strategy documents, account configuration or scheduler state. Implementation progress is recorded below.

Visitors should be able to answer: What does the agent own? What has it earned? Why did it act or choose not to act? What is it doing next?

Keep the handoff's compact design, Agent dashboard navigation label and restrained disclosures. Add the records and operational behavior needed to make that presentation reliable.

## Verified current state

Before implementation run `git status --short` and `git diff --stat 40b317b..HEAD -- app/public app/reason app/schemas app/storage app/policy app/broker app/dashboard public-ui ops`. Compare the functions below with the current code: the SHA alone doesn't capture initially untracked files. Preserve unrelated working-tree edits.

| Finding | Evidence | Impact | Effort / risk / confidence |
| --- | --- | --- | --- |
| Feed has no portfolio/mode scope; headline portfolio is paper | `app/public/projection.py:99` reads all public-summary decisions and paper holdings; `app/public/models.py:59` lacks identity | Live decisions can appear beside unrelated paper results | M / medium / high |
| Missing quotes distort totals and can conceal positions | `app/public/projection.py:124` requires a price table; `:137` uses `(price or 0)` | Missing prices can look like losses or no holdings | M / medium / high |
| History lacks timestamps, explicit inception and cash flows | `app/dashboard/queries.py:181` returns floats over all cached price dates; public return uses STARTING_CASH | Can't support honest live returns or date ranges | L / medium / high |
| Feed is unbounded and queries outcomes per record | `app/public/projection.py:107`, `_decision_item()`, `_outcomes()` | More history means growing payload and query cost | M / medium / high |
| Trace identity is ticker plus timestamp | `app/public/server.py:26`; `app/public/projection.py:196` returns first match | Ties and repeated same-ticker decisions can resolve incorrectly | M / medium / high |
| Latest position summary can become oldest | `app/public/projection.py:115`: `latest_summary = {item.ticker: item.public_summary for item in decisions}` over descending records | Incorrect narrative; frontend workaround relies on the full feed | S / low / high |
| Useful facts exist but aren't projected | Target weights in `app/schemas/decision_record.py:123`; reasons in `app/dashboard/queries.py:288`; run provenance at `:364` | Sizing and explanations are unnecessarily missing | M / medium / high |
| Full policy/stage metadata needs new records | `app/policy/decision_policy.py:32` stores approval/reasons only; decision schema has five text stages | Can't populate successful checks, versions or stage timings from existing data | L / medium / high |
| PREPARED doesn't establish active reasoning | `app/reason/run.py:159-180` timestamps intake preparation; `app/schemas/reasoning_run.py:8` lacks running/heartbeat | An abandoned prompt handoff could look active forever | L / medium / high |
| Investment reasoning isn't scheduled | `docs/reasoning/OPERATOR_GUIDE.md:77`; task installer only schedules the digester | Countdown can't currently promise a reasoning session | L / high for activation / high |
| Calendar has bounded coverage | `app/x/calendar.py:5-8`, ending 2026-12-31 with partial-year holidays | Future dates need explicit coverage and maintenance | M / medium / high |
| Public GET opens an initializing, write-capable connection | `app/public/server.py:23`; `app/storage/database.py:273` creates directories, schema and migrations | Unnecessary writes on reads; poor publication isolation | M / medium / high |
| UI requests once and has minimal routes/error states | `public-ui/src/App.tsx:48`, `:97`; `public-ui/src/main.tsx:5` | No refresh, persistent filters or distinct unavailable/offline/not-found behavior | M / low / high |

Host observation on September 5: all five installed `boustrategy-digester-*` tasks were Disabled. They still reported future NextRunTime values, including weekday triggers on the September 7 market holiday. No reasoning task was listed. Don't hardcode this transient observation; use it as a countdown test case.

## Decisions for all design gaps

| Handoff feature | Recommendation | Required behavior/data |
| --- | --- | --- |
| AUM | Rename Portfolio value or Live equity | Actual portfolio, currency and as-of time. AUM adds little clarity for this account. |
| Paper-only presentation | Replace as primary | One live BouStrategy account; explicit paper archive/mode. Missing live data must never silently fall back to paper. |
| Headline metrics | Revise | Portfolio value, selected-range return, decisions today. Move policy pass into reliability/policy detail: it isn't investment performance. |
| 30-day chart and today's gain | Add with proper accounting | Timestamped valuations, external flows, defined daily baseline and fee/dividend treatment. Show funding changes separately. |
| Allocation/deployed bars | Keep and expand | Real cash and holdings, theme exposure, then asset classes. Buying power isn't cash. Don't invent fixed-income/other slices. |
| Proposal sizing | Add from recorded facts | Proposed/final target weight and decision-time current weight if available; order size and executed size separate. A 5% target isn't a 5% order. |
| Feed status | Clarify | Action, policy outcome and execution outcome are different dimensions. Approved doesn't mean filled; held doesn't mean human review. |
| Position names/details | Add | Durable instrument metadata, quantity/price/cost when known, last reviewed thesis, relevant event and latest linked decision. |
| Thesis health | Add explicit review records | Not reviewed, intact, under review, invalidated; reviewed-at and evidence/run link. Don't infer intact from returns or an old BUY. |
| Position policy risks | Add with context | Current exposure observations separate from historical entry checks. Appreciation above an entry cap isn't necessarily a present violation. |
| Policy catalog/categories/versions/history | Add | Distinguish hard policy, posture guidance and execution controls. Actual rule scope, threshold, units, effective version and changes. |
| Rule values/headroom/last triggered | Add via ledger | Persist checks and input snapshots. Not applicable, missing input and failed differ. Headroom only for comparable numeric quantities. |
| Variant perception | Add | Consensus, disagreement, evidence and falsification conditions. Don't force six elaborate stages on every PASS or no-action result. |
| Stage summaries/evidence/structured output | Add | Explicit public summaries and stage-to-claim associations. Older records keep their original text with missing metadata labeled. |
| Overall confidence/deltas | Defer or replace | Final conviction rationale first. Claim scores, if shown, mean model-assessed evidence support. Don't average them into success probability. Numerical forecasts need an outcome, horizon and calibration history. |
| Trace/model/schema/policy identifiers | Add selectively | Stable public IDs and versions actually recorded. Model changes are annotations in a continuous account history. Unknown historical versions stay unknown. |
| Trigger narrative | Add dedicated public text | Why this session began; manual/scheduled/event/retry origin. Several triggers may lead to one review. |
| Source titles/links/excerpts | Add approved metadata | Canonical public URLs, publisher/type/date, eligible excerpt, durable references. Evidence support isn't trade conviction. |
| Regime bars/confidence | Keep evidence, change semantics | Raw value, points, units, raw/published regime and snapshot time. Define scales before drawing bars. Composite score isn't confidence. |
| Execution detail | Add progressively | Confirmed price/status first, then fill quantity/notional, fees and reconciliation. Canceled remainder may coexist with partial fills. |
| Slippage | Defer until reference exists | Side-adjusted comparison to a recorded arrival/preflight price using actual fills. Limit price alone isn't a suitable substitute. |
| Masked account number | Omit | Public portfolio alias is sufficient; account digits add no explanation. |
| Pipeline timeline | Add actual milestones | Persisted event timestamps, duration only with both endpoints, retries and honest gaps. Don't synthesize ten steps from one final status. |
| Artifact downloads | Add sanitized public export | Versioned JSON/CSV generated from public records. No raw prompts, bundles, local files, authenticated sources or worker logs. |
| X narrative | Add dedicated public summary | Its actual role: idea, corroboration, counter-thesis or crowding. Link eligible claims. |
| Add/trim/exit conditions | Keep | Compact disclosures linked to thesis reviews and holding history. |
| Motion | Keep restrained | Short transitions, loading feedback and disclosure controls. No fabricated typing, progress or market movement. |

## Policy recommendations

Numerical rules are revisitable. Neither an old spec nor a mockup establishes which investment constraints are best. These recommendations don't change enforcement in the current application.

| Topic | Recommendation |
| --- | --- |
| Schema, deterministic policy, account-bound preflight | Keep their distinct responsibilities. Show which stage prevented action. |
| Mockup 8% single-name / 20% sector caps | Don't adopt just to match the design. Review intended concentration, correlated themes, ETF overlap and drawdowns; expose diagnostic concentration first. |
| Existing 20% equity / 50% ETF / 60% theme limits | Treat as interim settings, version them and evaluate alternatives on documented scenarios. Historical proposal replay measures changed rejection behavior, not counterfactual investment performance. |
| Five-day minimum hold | Reject as a blanket hard gate. It can prevent an exit after thesis invalidation. If churn matters, measure reversals/turnover/fees and consider review requirements on repeated risk increases. |
| Blanket 2% order cap | Prefer deliberate notional/liquidity/spread/freshness controls separate from final position concentration. Don't silently clip an order into a different sizing decision. |
| Earnings blackout | Prefer a recorded event-risk review/rationale first. If a hard blackout is later selected, define event certainty, timezone and risk-increasing scope; preserve exits. |
| Cash floor | Don't add as a generic investment rule. Actual settlement, obligations and reserved orders govern spendable funds; exposure posture is a different concern. |
| 80% auto-approval confidence floor | Reject. No calibrated decision probability exists; an arbitrary model number shouldn't decide autonomy or human review. |
| 5% initial position floor | Keep as revisitable posture guidance, not a fabricated deterministic check. Record tier and rationale; evaluate transaction economics and concentration before hard enforcement. |
| Extraordinary-opportunity exceptions | Keep the concept with typed scope, evidence, authority and policy version; record expiry when applicable. Never bypass unrelated account/data/execution requirements. |
| Portfolio drawdown stop | Add monitoring and evaluate separately, not an automatic stop in this UI release. Distinguish adverse markets from broken/stale inputs. |
| Live ETF support | Deliberately resolve schema versus execution mismatch: decision schema allows ETFs; `app/broker/packet.py:34` rejects non-equities live. Recommend a separate ETF-capability/accounting test scope. No options/shorting/hedge overlays from the mockup. |
| Policy changes | Public change log, immutable versions and effective dates. Coordinate selected changes across docs, prompts, schemas and enforcement; old decisions retain their original evaluations. |

Don't optimize for 100% policy pass. Show proposal acceptance, missing-data failures, execution completion and no-action sessions with explicit denominators and periods. Rejection can demonstrate a working guardrail.

## Additional pages

Future navigation bookmark: Agent dashboard, Performance, Activity, Strategy. The maintainer deferred additional pages on September 5, 2026. Implement their underlying records and useful dashboard/detail controls now; keep standalone pages, archive navigation and comparison views for later.

| Page | Purpose | Timing |
| --- | --- | --- |
| Agent dashboard | Overview, current activity/next run, compact Feed and Positions; link Policies to Strategy | Keep home |
| Performance | Funding-adjusted live returns, benchmark comparison, drawdown, exposure, historical/closed holdings and methodology | After accounting is reliable |
| Activity | Scheduled/manual/event sessions, successful no-action outcomes, failures, retries and a next-session agenda | With actual runtime records |
| Strategy | Mandate, posture versus hard controls, actual policy catalog, evidence/regime methods and change history | With policy/provenance records |
| Decisions | Full searchable archive | Bookmarked for later; full-history search and pagination stay within Feed now |
| Research | Maintained watchlist, questions, catalysts and thesis reviews | Later; WATCHLIST decision enum alone isn't durable watchlist membership |
| Compare agents | Optional future comparison of genuinely separate comparable histories | Deferred, consistent with the one-account constraint |

Keep traces nested/directly linkable. No top-level Decision trace tab, duplicate Status page, generic news stream, public trading controls or misleading model leaderboard. Model switching on one account is an annotated timeline, not a controlled comparison.

## Acceptance behavior: feed and navigation

- Backend cursor pagination: 25 initially, maximum 100. Show more appends and retains focus/scroll; failure offers retry at that page. No endless auto-loading by default.
- Unique ordering tiebreaker and publication snapshot/high-water mark. Freeze result membership across pages or invalidate affected cursors explicitly when status/publication changes; never silently skip or duplicate rows.
- Search all published history: ticker, company, summary, theme. Exact ticker first. Filters: action, outcome, dates and paper/live scope. Agent filtering can stay internal until another real view exists.
- About 300ms debounce, Enter immediate, cancel obsolete requests and discard late responses. Bound/normalize queries and use parameterized escaped search. Start with SQLite search, not a new service.
- URLs persist tab/query/filters/range/scope. Back from a trace restores loaded pages and reading position. Browser Back/Forward and direct links work.
- New records while reading produce an N new updates control; don't move the content under the reader. Deduplicate by public ID/version. Headline metrics come from scoped server aggregates, not loaded-row counts.
- Group related records by run or offer a run filter. Successful no-action sessions belong in Activity and optionally one compact Feed summary, not a fake ticker decision.
- Distinguish empty database, no public decisions, nothing today and no filter matches. Clear filters is available for the last case.
- Long text, symbol punctuation, renames/delistings, tied timestamps, absent metadata and old schemas remain readable. Link by stable ID rather than ticker/time.
- Not-found, malformed URL, ambiguous legacy link, unpublished and retracted record have deliberate behavior. Unpublished IDs return 404. Formerly published content follows a chosen tombstone policy and cache invalidation; don't resolve ambiguity arbitrarily.

## Acceptance behavior: portfolio and performance

- Differentiate not configured, not funded, funded with zero positions, all positions sold, unavailable holdings, partial valuation and complete valuation. Zero positions isn't an error. 100% cash requires actual complete balances.
- Return holdings even without quotes. Each valuation includes time, source and quality. Suppress totals/returns requiring an incomplete denominator; show valid balances and last complete valuation separately.
- Cash, buying power, unsettled proceeds, reserved funds and unexplained residuals aren't interchangeable. Never silently label residual equity as cash.
- Durable funding/fill/corporate-action records cover deposits, withdrawals, dividends, fees, transfers, splits and corrections. External/manual broker trades are reconciled, not falsely attributed to an agent decision.
- Agent performance uses linked subperiod returns with external flows removed. Capture valuations at the required boundaries; sparse snapshots alone don't recover exact returns. If approximating, state the convention and limitations explicitly.
- Daily P&L uses the previous eligible session-close baseline and external-flow adjustments. Fees/dividends use one declared treatment; funding changes display separately. Show currency and pricing session.
- Start with 1M, 3M, YTD, All. Add 1D only with actual intraday observations. Use timestamp spacing, honest gaps and correct inception; don't create pre-inception performance from unrelated price history.
- Cover no/single/flat observations, extreme drawdowns, signed zero, missing benchmark dates and short track records. No annualized headline from a tiny sample.
- QQQ primary benchmark, SPY/SMH optional, with shared dates and compatible return convention. Price-only and total-return inputs are labeled distinctly. Deposits don't become alpha.
- Closed holdings have history; reopening a ticker creates a new holding episode. Thesis reviews attach to explicit identities rather than ticker strings.
- Partial fill, canceled remainder, delayed settlement, duplicated broker event, late correction, unknown cost basis, split and transferred position are separate test cases. Requested notional mustn't masquerade as filled notional.

## Acceptance behavior: activity and synchronized scheduling

Use separate dimensions:

| Dimension | Proposed states/facts |
| --- | --- |
| Schedule | manual, scheduled, paused, unavailable; enabled state and revision |
| Occurrence | due time, eligible session, prerequisites, origin, skipped reason |
| Attempt lifecycle | queued, preparing, ready, running, completed, failed, canceled, timed out |
| Reported phase | gathering inputs, reviewing holdings, researching, validating, finalizing; unknown remains absent |
| Business result | no action, decisions authored, incomplete; preserve saved decisions even after failure |
| Freshness | server time, observed time, worker/scheduler heartbeat, revision and stale reason |

- Actual runner start/phase/heartbeat events power status. PREPARED means ready, not running. Don't retroactively turn old preparation timestamps into actual start times.
- Activity strip example: Researching candidates · started 4 minutes ago · last update 12 seconds ago. Show recorded structured milestones and approved summaries, not private model reasoning, raw tool output or fictional percentages.
- No action is successful and visible: Reviewed holdings; no changes warranted. Failed sessions retain any authored decisions and show incomplete outcome.
- Separate logical occurrence, run and retry-attempt IDs. Preserve attempts; show Completed after retry. Use leases/fencing and one active attempt per scope to reject late writes from superseded workers. Never blindly retry an uncertain order submission.
- Stale heartbeat first means Activity update delayed. Runner reconciliation establishes timeout; browser disconnection doesn't establish worker death. Paused future scheduling may coexist with a running attempt.
- One server-side schedule authority supplies worker and public API. Include configured intent, actual enabled state, market eligibility, prerequisites and observation freshness. Poll task metadata outside public requests.
- Recommended cadence: successful shared intake makes a reasoning occurrence eligible; retain explicitly identified manual/event jobs. Don't reuse raw digester times as promised reasoning starts.
- Define a late-run grace window; catch up once when appropriate, otherwise record skipped. Don't replay every missed session after downtime. Manual/scheduled overlaps must be deduplicated deliberately.
- Public countdown receives server_now, next_due_at, eligibility/dependency status, timezone, mode and revision. Use server-clock offset and monotonic elapsed time locally; resync on wake/focus/reconnect/change, without one API call per second.
- At zero refetch and show Awaiting start, Waiting for inputs, Delayed, Paused or Running. Don't optimistically restart tomorrow's countdown.
- Test DST, visitor timezone, holiday/early close, weekend/Sunday research, calendar coverage expiry, disabled task with future NextRunTime, stale data, schedule edits and machine outage.
- Build a non-mutating schedule preview first. Actual unattended reasoning is an operating feature distinct from its public display. The public app must never activate scheduling or place trades.

## Acceptance behavior: errors, updates and delivery

- Load sections independently. Failed chart doesn't erase Feed; failed schedule doesn't erase holdings. Cover loading, valid empty, partial, stale, offline, not-found, retracted, rate-limited and server-error states.
- Refresh errors retain the last valid result with its as-of time and local retry. Respect Retry-After, use backoff/jitter, and pause unnecessary hidden-tab work. Initial targets: activity every 5 seconds when active, overview every 30 seconds while visible; measure and adjust.
- Use conditional HTTP requests and shared caching before WebSockets. Add SSE later only if measured needs justify it. This product doesn't need token streaming.
- Public allowlists cover free text as well as fields. A thesis paragraph can contain private source content; source_claim.public_safe alone doesn't establish paragraph eligibility. Publish dedicated public summaries where necessary.
- Public reads never call a broker, launch work, run schema migrations or serialize raw internal errors. Open published data read-only and explicitly close connections. Trusted pipeline hooks perform publication writes.
- Search snippets, exports and share metadata use the same publication contract. Escape text; allow approved public URL schemes; invalidate caches after retraction. API typos mustn't return the SPA with HTTP 200.
- Include React error boundaries, page/section retry, explicit freshness, useful not-found pages and old-schema rendering. A malformed record is an observable publication error, not silently discarded corruption.
- Test keyboard focus, touch targets, 200% zoom, 320px screens, color-independent status, text/table chart alternatives and reduced motion. Announce batches of updates, not every countdown second. Hover tooltips need focus/touch equivalents.
- Preserve accordion state on refresh if the record hasn't changed. Keep scroll position during pagination and live updates. Long reading sessions shouldn't accumulate unbounded browser data.
- Test large datasets before adding virtualization. Bound query work and response size first. Keep internal correlation IDs in logs without exposing private error detail.

## Public architecture

Keep Python/FastAPI/SQLite and React/TypeScript. No frontend framework rewrite or distributed workflow infrastructure is required.

Build explicit public portfolio identity even though only one live account is displayed. Historical model identity belongs on runs/decisions; current portfolio identity belongs on balances. A model change doesn't reset returns. Unassigned legacy decisions remain explicitly unassigned unless provenance establishes their scope.

Use versioned public contracts, preferably v2 with a legacy-link compatibility path. Suggested resources:

- `GET /api/public/v2/portfolios`: eligible public aliases, mode and capabilities; one live profile initially.
- `GET /api/public/v2/portfolios/{id}/overview`: scoped metrics, freshness and section availability.
- `GET /api/public/v2/decisions?...`: bounded cursor/search/filter page, snapshot marker and next cursor.
- `GET /api/public/v2/decisions/{public_id}`: decision content plus versioned public execution/publication updates.
- `GET /api/public/v2/portfolios/{id}/positions` and `/performance?range=...`: balance/valuation data and methodology.
- `GET /api/public/v2/activity?...` and `/schedule?portfolio_id=...`: sessions/attempts and scheduler status.
- `GET /api/public/v2/policies?...`: versioned catalog and selected historical/current observations.
- `GET /api/public/v2/decisions/{public_id}/export`: sanitized public JSON, not a filesystem artifact path.

Shared metadata: API/public revision, generated_at/server_now, data_as_of, scope, status/reason. Null isn't zero. UTC instants and explicit New York session dates; money precision defined at the accounting boundary, rounding at display. No broker account aliases/fingerprints in public IDs.

Recommend an incrementally maintained public read model in a separate SQLite store for publication/search/metric snapshots. Publish idempotently by source revision to stable public ID, expose projection lag, and keep GET bounded/read-only. Historical compatibility adapters belong at the publication boundary. Don't rewrite old decisions to manufacture fields.

Define publication consistency across page cursors, current statuses and revocations. A high-water ID alone isn't enough if later status changes alter a filtered page's membership. Preserve the query snapshot or issue a clear restart-required response.

## Implementation phases

One self-contained plan covers the whole requested scope. Each phase is a separate reviewable change. Phase 1 is foundational; 2, 3 and 4 can proceed independently afterward; 5 consumes their contracts. Build Phase 6's tests throughout rather than postponing correctness until release.

### Phase 1: Public identity, publication and scalable reads

Scope: `app/public/`, new public query/store modules there, `tests/public/`, `public-ui/src/types.ts`, feed/routing integration in `public-ui/src/`. Extend trusted publication hooks in `app/state/pipeline.py`/`app/storage/records.py` only as needed; preserve execution behavior.

1. Define portfolio/mode, public IDs and publication revisions. Avoid guessing scope from ticker/date. Keep v1 links compatible when unambiguous; fail clearly when not.
2. Add idempotent publication, public-safe field classification, read-only query connections, revocation and old-schema adapters. No writes through GET.
3. Fix holdings availability and latest summary selection. Latest position links come from their own scoped query, not the loaded Feed page.
4. Add indexed bounded pagination/search/filter queries and independent aggregates. Remove query growth per feed row and whole-history equity replay from overview requests.
5. Define section status/error contracts and real unknown-route handling, including the production SPA mount.

Verification: `python -m pytest -q tests/public`; frontend tests/type-check below. Seed 100,000 synthetic records in a disposable database; test bounded result count, snapshot continuation without omission/duplication, indexed query plans, consistent counters and query count that doesn't grow once per returned row. Include tied timestamps, concurrent publication, stale cursor, mode isolation and retraction.

### Phase 2: Live accounting and performance

Scope: reporting additions in `app/schemas/live_execution.py`, trusted ingestion in `app/storage/records.py`, new `app/performance/` if appropriate, public projections; `app/paper/broker.py` only for explicit paper-reporting integration. Tests under `tests/public/`, `tests/storage/`, `tests/schemas/`, and new `tests/performance/`.

1. Define balance, funding, fill and completeness records before returns. Don't weaken execution preflight's positive-equity requirements merely to display an unfunded account; reporting has different requirements.
2. Ingest actual cash/quantity/cost/timestamps when supported. Otherwise publish partial capabilities. Reconcile funding/external activity with stable IDs and corrections.
3. Materialize timestamped valuations, inception and session-close baselines. Capture flow-boundary values where the chosen return convention requires them.
4. Implement exact reference-tested daily P&L and linked returns only for supported intervals. Add benchmarks using compatible dates and conventions.
5. Publish holdings, closed episodes, allocation, history and methodology; keep paper scope separate.

Verification: focused schema/storage/public/performance tests. Include deposit-only balance increase with zero investment return, withdrawal, gain, fee, dividend, split, missing/stale quote, all-cash, sold-out, partial fill and correction. Each calculation convention needs a worked numerical reference test. Old observations remain immutable after corrections.

### Phase 3: Explanations, policy ledger and thesis history

Scope: `app/schemas/decision_record.py`, new supporting schemas, `app/policy/decision_policy.py`, `app/state/pipeline.py`, `app/storage/`, trusted output ingestion in `app/reason/`, `app/public/` and mirrored tests.

1. Publish eligible existing sizing, safe rejection-code explanations, milestones and model provenance. Don't expose arbitrary event-detail strings.
2. Add a policy evaluation ledger: rule/version/type, scope, applicability, observation, threshold/unit, result, evaluated_at, exact input snapshot and exception reference.
3. Bind versions and snapshots at evaluation time. Historical unknown stays unknown. Avoid selecting a same-day regime observation created after the decision; exact snapshot binding is the target, chronological lookup only an explicitly labeled legacy fallback.
4. Extend optional public decision fields with variant perception, stage summaries, evidence associations, approved trigger/X text and public source registry. Missing historical/non-action stages remain legitimate.
5. Add holding-thesis review events with evidence, conditions and reviewed-at identity. Latest ticker decision isn't equivalent to current thesis health.
6. Project confirmed execution/fill records and sanitized exports. Slippage waits for a documented reference price and complete fill facts.

Verification: regression fixtures prove recording hasn't changed existing policy approval/rejection behavior. Test rule applicability/missing data, exact units/thresholds, version binding, public leakage sentinels in every narrative/export, partial-fill cancellation, absent stage fields and public export/UI parity.

Strategy changes remain separate: if selected, update rule definitions, prompts, documents and code under one effective version. The user's flexibility authorizes reevaluation here, not unannounced changes to live enforcement.

### Phase 4: Actual activity and synchronized scheduling

Scope: `app/schemas/reasoning_run.py`, `app/reason/`, `app/storage/`, new attempt/schedule modules, `app/x/calendar.py`, narrowly scoped trusted `ops/` integration, `app/public/`, and mirrored run/storage/schema/public/calendar/scheduler tests.

1. Add lifecycle/attempt reporting while preserving PREPARED compatibility. Separate prepared_at from actual started_at, phase, heartbeat and terminal time.
2. Add occurrence/attempt identity, leases/fencing, duplicate-start prevention and recovery. Preserve current run/decision links through additive migration; don't change namespace semantics casually.
3. Ship truthful manual-mode status and completed no-action sessions immediately, before unattended scheduling exists.
4. Add versioned calendar coverage and schedule definitions consumed by the runner. Preview eligible occurrences and detect disabled tasks/drift. Define prerequisites, concurrency, late grace and skip rules.
5. Integrate an actual supported agent runner at its start/completion boundary. If stage callbacks aren't available, report coarse real lifecycle only. The prompt-copy handoff isn't an unattended runner; resolve platform constraints explicitly.
6. Publish scheduler/worker status and server-authoritative countdown data. Enablement and permitted job scope are explicit operating decisions, never public GET side effects.

Verification: injected clocks, fake runner/scheduler adapter; duplicate start, partial failure, stale heartbeat, late superseded completion, dependency failure, pause during run, missed windows, overlap, DST, holidays, early close, calendar expiry and disabled future NextRunTime. No real trading or agent spending in automated tests.

### Phase 5: Complete the existing dashboard and decision detail

Scope: `public-ui/src/`, routing/testing configuration only as needed, public API integration fixtures and `public-ui/README.md`. Preserve `styles.css` tokens and handoff profile/header layout.

1. Semantic routes and URLs, portfolio/mode scope, cursor navigation and state restoration. Split App.tsx by actual page responsibility, not speculative abstractions.
2. Search, Show more, new-update banners and all request states; use scoped server metrics.
3. Activity strip/countdown and session disclosures on the dashboard, with restrained accessible announcements. The standalone Activity page is bookmarked for later.
4. Performance and policy disclosures on the existing dashboard, backed by the real contracts. Missing capabilities stay local to affected sections. Standalone Performance and Strategy pages are bookmarked for later.
5. Richer trace, policy and position disclosures; preserve focus, scroll and expansions through refresh. Add export/share links.
6. Present one live account; annotate historical model changes. Keep paper distinguishable at each entry point and comparison navigation absent.

Verification: UI test/lint/type-check/build commands below. Browser tests cover canceled/out-of-order searches, repeated/failed Show more, updates during reading, Back/Forward/direct links, clock skew, reduced motion, keyboard/touch, zoom and 320/375/768/1200px layouts.

### Phase 6: Release matrix and operations

Scope: integration/browser tests, test configuration/fixtures, public error/cache behavior and runbooks. No new feature scope here.

1. Create deterministic fixtures for each acceptance-state group. Use existing plain pytest and React testing patterns.
2. Test API/publication isolation, SQLite concurrency, browser journeys and exports with malicious/private sentinel text. Test unknown API and asset routes with the built SPA present.
3. Exercise restart/recovery, partial publication, old schemas, delayed data, corrections and retraction cache invalidation. Attempt IDs survive restarts.
4. Benchmark on an identified test machine. Initial target: cached overview/feed p95 below 500ms at 20 concurrent clients over 100,000 records, bounded response size and zero writes by GET. Record p50/p95/query counts; investigate query plans/materialization if missed.
5. Read-only production smoke against actual records: verify live/paper scope, model identity, valuation freshness, trace links and absence of internal operator/broker routes.

## Commands, conventions and release gates

During implementation only, install if needed: `python -m pip install -e .[dev]` and `npm --prefix public-ui ci`.

Conventions: plain pytest arrange/act/assert functions; lowercase snake_case rejection codes; Pydantic validates shape/local consistency, policy evaluates rules; catch actual failure boundaries without swallowing corruption. Exemplar files: `tests/public/test_public_dashboard.py`, `tests/policy/test_decision_policy.py`, `tests/storage/test_live_reasoning_records.py`, `public-ui/src/main.test.tsx`.

Each phase runs focused tests. Final checks, expected exit 0:

- `python -m pytest -q`
- `python -m ruff check .`
- `python -m ruff format --check .`
- `python -m mypy app tests`
- `npm --prefix public-ui run test`
- `npm --prefix public-ui run type-check`
- `npm --prefix public-ui run lint`
- `npm --prefix public-ui run build`
- `git diff --check`

Done means every acceptance-state group has a test/fixture or an explicit deferred-feature decision; no production mock fallback; historical records readable; scoped identity correct; public reads bounded/read-only; approved strategy changes versioned coherently; browser and actual-record smoke checks pass.

Stop and report if live data can't support the return convention, required runtime APIs aren't available, publication requires private source disclosure, or a display change would alter trading permissions. Identify unrelated baseline check failures rather than rewriting someone else's work. No scheduler/account/broker activation to satisfy a UI test.

No commits, pushes, merges or deployment are required by this plan. Use an isolated branch/worktree when needed to preserve unfinished changes. Keep phase changes independently reviewable and update this plan's status without erasing original evidence.

## Sources and scope limits

External references checked for the accounting and schedule design:

- [GIPS handbook](https://www.gipsstandards.org/standards/gips-standards-for-firms/gips-standards-handbook-for-firms/): subperiod linking and external cash flows inform the return metric. This isn't a claim of GIPS compliance.
- [NYSE hours and calendars](https://www.nyse.com/markets/hours-calendars): authoritative sessions, holidays and early closes with explicit coverage dates.
- [Microsoft StartWhenAvailable](https://learn.microsoft.com/en-us/windows/win32/taskschd/tasksettings-startwhenavailable): missed scheduled work can be queued and run later, reinforcing the distinction between due time and actual start.

Reviewed: public UI/API, relevant internal dashboard queries, decision/policy/regime schemas, live balance/execution models, run/pipeline storage, scheduling scripts/calendar, related tests and prior plans. Read-only product/data-flow review, not a full security audit, broker/account reconciliation, strategy backtest, dependency advisory audit or measured load test. Planned acceptance cases aren't claims that every case is a current defect.

Deferred intentionally: live token streaming, confidence leaderboards, automatic policy tuning, options/shorting, public trade controls, distributed workflow-engine infrastructure, mandatory virtualization and agent comparisons before comparable independent histories exist.


## Execution progress

Started September 5, 2026 after maintainer approval. Additional standalone pages are deferred.

| Work | Status |
| --- | --- |
| Public identity, publication and bounded reads | Backend reviewed and integrated; publication lifecycle follows in runtime phase |
| Live accounting and performance | Reviewed and integrated; calendar binding follows in Phase 4 |
| Explanations, evaluations and thesis history | Reviewed and integrated |
| Activity and scheduler integration | Reviewed and integrated; schedules stay manual/inactive |
| Existing dashboard/trace experience and edge cases | Reviewed and integrated (Phase 5) |
| Release checks and browser verification | Reviewed and integrated (Phase 6) |
| Whole-codebase audit and focused simplification | Complete, integrated in main |
| Execution/scheduling/private-dashboard reevaluation | Complete; recommended controls and activation prerequisites documented |

The executor checkout starts from the existing working tree. Source changes are reviewed and
integrated phase by phase. No account settings, live tasks or orders are changed by verification.

Phase 1 review: 18 public tests passed. Scoped Ruff, formatting and mypy passed.
Independent benchmark: 100,000 records, 20 concurrent clients, 100 requests,
p50 136.33 ms and p95 201.42 ms, six SQL statements and 25 rows per feed request.
The trusted publisher currently reconciles history; incremental publication and
automatic refresh are tracked for runtime/release integration.



Phase 2 review: full Python suite passed 384 tests. Full Ruff, formatting and
mypy passed. Accounting covers immutable corrections, flow boundaries, nullable
fees, holding episodes, bounded charts and quarantined paper/live contamination.
Actual legacy live snapshots remain partial, with no invented return history.

Phase 3 review: independent full suite passed 403 tests before the final additions;
16 focused explanation tests passed after those additions. Executor full suite
passed 404 tests. Full Ruff, formatting and mypy passed. Policy behavior matched
26,460 cases. Independent corrected query benchmark: 100,000 records, 20 clients,
p50 208.51 ms, p95 296.01 ms, seven SQL statements, 25 rows, 10,081-byte maximum
feed payload. This measures query calls; HTTP measurement follows in release checks.

Additional Phase 3 verification: independent primary suite passed all 404 tests in an isolated clean dependency environment. No global Python packages changed.

Execution resumed September 6 after a tool usage interruption. Phase 4 work remains
in the isolated executor checkout pending review; it hasn't been integrated or
activated. The source database still contains two decisions, one live snapshot,
and no live reasoning runs, broker execution records or paper fills.

Phase 4 review checkpoint: eight activity/scheduler tests passed independently,
including concurrent occurrence claims, restart reuse, public retry history and
scope withdrawal. Final review still covers live retry/freshness behavior,
legacy run-link continuity, producer measurements and the complete check suite.

Phase 4 review and integration (September 6, 2026, completed by a second reviewer after
the original parent session hit a usage limit): reviewed the isolated executor checkout at
scratchpad/public-product-executor, including the live freshness recheck and explicit retry
test, legacy run-link continuity, lease fencing, and the live readiness gate. LIVE_SNAPSHOT_MAX_AGE,
decision_policy.py, live_execution.py and the chosen execution settings are unchanged. Two E501
line-length findings in tests/reason/test_runtime.py were wrapped; no behavior changed.
Independent producer benchmark on this host (Windows Server 2019, Python 3.14.2, 100,000
records): initial publication 44.35 s while 434 source heartbeats continued at p50 1.42 ms and
p95 3.68 ms; a heartbeat-only republish took 21.6 ms and validated zero decisions; one changed
decision republished in 79.0 ms validating exactly one record. Forty-eight reviewed files were
copied into the main working tree (app, tests, docs/reasoning, docs/reporting.md,
ops/runtime.schedule.example.json). Main-tree checks after integration: pytest 450 passed,
Ruff lint clean, Ruff format clean for app and tests, mypy clean over 158 files,
git diff --check clean, public-ui test (6 passed), type-check and lint clean. No commit was made.
Source database, live profiles and disabled digester tasks were not modified. Windows tasks
remain uninstalled for runtime; schedule revisions stay manual.

Note on Ruff formatting: `python -m ruff format --check .` now also inspects Markdown code
fences and fails on historical plans; the Python scope `app tests` is what was verified.

Phase 5 review and integration (September 7, 2026): completed the existing dashboard and nested
decision trace against the version 2 public contracts. The release keeps Live account first, clearly
separates Paper simulation, preserves URL and reading state, bounds full-history feed browsing, and
shows independent performance, positions, policies, activity, and trace request states. The only
backend addition is exact legacy decision-link resolution with clear ambiguous, missing, and
withdrawn outcomes. Standalone Performance, Activity, Strategy, Decisions archive, and comparison
pages remain bookmarked.

Independent checks passed in the executor checkout and again after copying the 24 reviewed files into
the main tree: 25 React tests, 45 public Python tests, TypeScript type-check, ESLint, production build,
scoped Ruff lint and formatting, scoped mypy, and `git diff --check`. Final Chromium review covered
fixture and actual published states at 320, 375, 768, and 1200px, keyboard entry, simulated 200%
CSS zoom, direct routes, Back scroll restoration, search, filtering, repeated pagination, legacy
links, paper attempts, exports, and retraction cleanup. Document width stayed within each viewport;
wide tables use their labeled horizontal scroll region. The actual source remains partial and stale,
with no published live return history or active schedule. No task, broker, account, source database,
or deployment setting changed.

Phase 6 review and integration (September 7, 2026): added release-level coverage for built-SPA and
API route isolation, zero-write GET and HEAD behavior, publication rollback and retry, concurrent
reader consistency, and escaped approved public text. The release benchmark now runs through a real
localhost Uvicorn server over 100,000 rich decision records with explicit compact feed rows. Its
first run found an unbounded overview aggregation. Decision totals and daily counts are now
materialized during trusted publication, recomputed after revocation, and read with an old-store
fallback. Summary requests also skip position-link refresh work that they discard.

Independent main-tree checks passed: 457 Python tests, 26 React tests, full Ruff lint and formatting,
strict mypy over 160 source files, TypeScript type-check, ESLint, production build, and
`git diff --check`. A fresh independent benchmark measured feed p50 281.227 ms and p95 357.764 ms,
overview p50 45.508 ms and p95 54.445 ms, seven direct-feed SQL statements, four direct-overview SQL
statements, 25 returned feed rows, and bounded response sizes. The database checksum stayed unchanged
and no WAL or SHM sidecars appeared. `docs/public-release.md` records release, smoke, backup, restore,
and retraction procedures. No actual source, task, broker, account, or deployment state changed.


### Audit, refactor and operating assessment completion (September 8, 2026)

Completed the sequential execution/economic, paper, lifetime, I/O, readability and
public/accounting/runtime review in main. The phase executor checkout remains the
pre-audit baseline. Concrete findings and retained choices are recorded in
[`docs/plan-031-audit.md`](../docs/plan-031-audit.md); the final operating recommendation is in
[`docs/execution-assessment.md`](../docs/execution-assessment.md).

The audit binds packets to the approved action/target and quoted ticker; rejects
non-finite economic inputs; serializes broker lifecycle validation; removes new paper
fill sizing lookahead; rejects unaffordable buys; makes settlement/rebuild atomic;
preserves approved watchlist entries; secures labeling markup and thread mutations;
protects newsletter archive recovery; preserves bounded X pagination checkpoints;
uses eligible replay horizons; closes private/CLI connections; displays actual runtime
attempts; and tightens reporting precision, flow boundaries and historical regime handling.
Unchanged live quota/session/regime safeguards were verified rather than duplicated.

Measured accounting producer work fell from 4.036 s to 0.152 s for the synthetic
2,000-point flat-account workload by removing repeated account validation. No generic
cache or service framework was introduced. Publication checkpoint version 7 refreshes
old projections. New paper simulation semantics are explicitly versioned; old fills
remain unchanged and incompatible paper benchmark comparisons are withheld.

Final gates passed in the isolated corrected dependency environment: 506 Python tests,
26 React tests, Ruff lint and full formatting check, strict mypy over 160 files,
TypeScript, ESLint, build and `git diff --check`. The full Ruff command now explicitly
excludes Markdown examples so newer formatter discovery does not rewrite historical
plans or protected prompts. Two upstream test-client deprecation warnings remain.
Policy parity matched all 26,460 cases and the recorded digest. Protected strategy,
prompt and evaluator files match the phase baseline after line-ending normalization.

The final module HTTP benchmark over 100,000 rich records, 20 clients and 100 requests
per route measured feed p50/p95 293.602/370.728 ms and overview 57.069/71.770 ms. Seven
feed and four overview SQL statements, bounded payloads, unchanged database checksum
and no WAL/SHM files were verified. The release runbook preserves earlier measurements
and adds this audit result.

Read-only host inspection still found five disabled digester tasks, two decisions,
one stale live snapshot, no broker records and no paper fills. Runtime tables are not
yet initialized in the actual source. The private configuration was not read or changed.
No source writes, real publication, models, broker calls, activation, commit, push or
deployment occurred. The task installer now defaults to disabled registration, but was
only parsed, never run.

Recommendation: use the private dashboard as an authenticated operator interface over
the existing persisted runtime, with readiness/preview, Run now, pause, named
cancel/retry, diagnostics, publication lag and broker reconciliation. Implement those
controls as separate follow-up work. Fresh snapshots, independent research evidence,
collector/reconciliation capability and staged paper operating evidence precede
unattended live activation. Preserve no extra trade approval, $20 max notional,
60-second quote age and 50-bps spread. Additional standalone pages remain deferred.
