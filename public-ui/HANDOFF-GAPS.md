# Public dashboard handoff gaps

Reference: `BouStrategy Handoff Spec.html`, downloaded September 5, 2026.

The dashboard keeps the handoff's compact 680px dark column, IBM Plex typography, square chart mark,
20px profile heading, handle, bio, and restrained disclosures. Agent dashboard is the only top-level
navigation label. The mockup's Decision Trace header was design navigation, so decision traces open
from real feed and position links instead.

## Implemented in this release

| Design goal | Current behavior |
| --- | --- |
| Live portfolio first | Live is the default scope. Paper simulation uses separate requests, URL state, labels, and cached records. Model changes are annotations within one continuous account history. |
| Useful headline metrics | The header shows recorded portfolio value, the selected-range investment return, and public decisions today. Null money stays unavailable instead of becoming zero. |
| Performance history | 1M, 3M, YTD, and All ranges use timestamped observations, explicit actual dates, flow-adjusted return, funding change, observed drawdown, compatible benchmarks, and gap-preserving charts. An accessible data table carries the exact values. |
| Allocation | Recorded cash and asset-class values are shown only when they reconcile to the portfolio. Buying power isn't presented as cash. |
| Crowded feed | Server-side full-history search and filters use bounded pages. Show more is locked while loading, retries locally, deduplicates rows, and stops at a disclosed 500-record browser window. New publications wait behind an update button so reading position doesn't jump. |
| Durable navigation | Scope, tab, search, filters, dates, performance range, and public run filter live in the URL. Back and Forward restore loaded feed pages and reading position. Stable opaque decision URLs coexist with exact legacy-link resolution. |
| Positions and holding history | Positions show company, quantity, price, cost, quote time and quality, weight, asset class, theme, holding episode, latest linked decision, and the latest explicit public thesis review. Empty states distinguish unfunded, all-cash, sold-out, unavailable, and observed zero-position accounts. |
| Policy detail | The policy view uses the published catalog, categories, versions, real rule observations, applicability, and comparable numeric headroom. Entry checks remain separate from current exposure observations. |
| Runtime activity | The strip shows persisted coarse stages, no-action and retry history, public run links, and a server-clock-based countdown only when fresh schedule authority supplies a due time. Manual, paused, disabled, stale, missing, and expired authority don't get a rolling timer. |
| Decision trace | The detail view uses published stages, variant perception, claims, approved source metadata, rule ledger, regime evidence, model provenance, execution facts, milestones, conditions, and sanitized JSON or CSV exports. Missing historical sections say so. Source links allow only public HTTP or HTTPS URLs without embedded credentials. |
| Publication changes | Pagination revision conflicts require an explicit restart. A retracted detail returns 410, clears the displayed trace, invalidates loaded feed snippets, and removes export controls. |
| Failure and access states | Overview, performance, activity, feed, positions, policy, and trace requests fail independently. Transient refresh failures retain and label last-good data. Offline, rate-limit, malformed, not-found, withdrawn, empty, partial, and no-match states have specific behavior. The UI has a skip link, visible focus, native disclosures, touch-sized controls, reduced-motion support, and contained wide tables. |

## Deliberate differences from the handoff

- The dashboard says Portfolio value or Paper equity rather than AUM. This is one account, not a fund
  presentation.
- Action, policy approval, and execution are separate facts. Approved doesn't mean filled, and a
  no-action review doesn't create a synthetic HOLD decision.
- The handoff's example policy limits, confidence gate, blackout, cash floor, minimum hold, override
  controls, account digits, trades, dates, and version strings aren't application data. The public view
  reports the versioned rules and observations that were actually recorded.
- Composite regime scores are evidence, not confidence. The UI reports raw and published state,
  components, units, points, and observation time when available.
- Motion is limited to short reveals, loading feedback, disclosure chevrons, and focus or hover
  feedback. The application doesn't simulate thinking, token streaming, progress, or market movement.
- Performance, Activity, Strategy, Decisions archive, and model-comparison pages remain bookmarked.
  Their underlying records and dashboard controls are present, but this release doesn't add those
  standalone pages.

## Data and operating prerequisites

- Live value, cash, allocation, quantities, cost, returns, daily P&L, benchmark comparisons, and
  holding history depend on published reporting observations with the required completeness and
  coverage. A legacy broker snapshot can establish observed holdings while cash, quantity, cost, and
  return remain unknown.
- Older decisions can lack public narrative, source, policy-ledger, model, execution, milestone, or
  thesis-review metadata. Publication doesn't invent those facts.
- A countdown requires an enabled scheduled revision plus a fresh scheduler observation. The runtime
  command is a one-shot worker, so an external supervisor must invoke its scheduler polling cadence.
  Schedules remain manual or inactive until the operator deliberately configures and enables them.
- Agent authoring receives approved source excerpts and recorded portfolio facts. Automated collection
  of outside research for an investment run is a separate capability.
- Public freshness depends on running the trusted publisher. The browser reads the isolated public
  database and can't repair stale source data or trigger publication.
- Runtime cancellation stops reasoning work. It doesn't cancel an order that has already reached the
  broker, and retrying an uncertain broker submission needs reconciliation first.

## Verification coverage

The release uses realistic generated version 2 fixtures without a production mock fallback. React
tests cover scoped loading, URL and history restoration, out-of-order search, pagination retries,
new-record notices, revision conflicts, partial and zero balances, stale retained data, rate limiting,
runtime clock skew, missing schedule authority, 404 and 410 traces, retraction cache clearing, legacy
links, safe long sources, CSV export, exact decimals, and chart gaps. Public API tests cover the same
contracts at the publication boundary, including exact legacy resolution and partial reporting.

Browser review covers dashboard and trace views at 320, 375, 768, and 1200px, reduced motion,
keyboard disclosures, back-scroll restoration, direct routes, search and filter states, paper attempt
history, safe exports, and retraction cleanup. Fixture review isn't evidence that the current live
source has complete reporting or an active schedule.

The release benchmark exercises real localhost HTTP reads over 100,000 rich decision records with
20 concurrent clients. Feed p95 was 426.470 ms and overview p95 was 55.094 ms on the recorded test
host, with bounded responses and no database writes or sidecars from GET requests. See
[`docs/public-release.md`](../docs/public-release.md) for the release matrix, exact measurements,
production smoke steps, and recovery procedure.


Audit follow-up, September 8: the zero-position message also covers a previously funded
account now at zero balance. Paper simulation disclosures distinguish immutable legacy
fills from new opening-price sizing, and incompatible paper benchmarks remain unavailable.
The complete audit passed 506 Python and 26 React tests; the final HTTP feed/overview p95
was 370.728/71.770 ms. No additional pages or navigation labels were added. See the
[audit record](../docs/plan-031-audit.md) and [operating assessment](../docs/execution-assessment.md).
