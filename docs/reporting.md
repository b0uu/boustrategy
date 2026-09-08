# Reporting ingestion and return methodology

Reporting records describe observed account facts. They don't authorize orders or
change execution preflight. An unfunded account can have a zero reporting balance;
execution snapshots still require positive equity.

## Ingest account observations

Use a JSON array of observations and the trusted local ingestion command:

```powershell
python -m app.performance.storage --db data/boustrategy.db --input observations.json --mode live --account-id 0123456789abcdef
```

For live reporting, `account_id` is the existing broker account fingerprint. It
stays internal. The input account and mode must match the command. Paper reporting
uses `--mode paper --account-id paper`. No command here contacts a broker or
changes scheduling.

Every observation has an immutable `observation_id`, a stable upstream
`external_event_id`, an account/mode, UTC-aware `occurred_at` and `recorded_at`,
and a `kind`. Supported kinds are `valuation`, `flow`, `fill`, `corporate_action`
and `coverage`. USD amounts accept decimal strings at cent precision. Quantities and prices
retain up to 18 decimal places, including existing cached float representations. Rounding uses half-even.
JSON serialization keeps decimal values as strings.

A minimal complete valuation looks like this:

```json
[
  {
    "kind": "valuation",
    "observation_id": "close-2026-06-10-v1",
    "external_event_id": "close-2026-06-10",
    "mode": "live",
    "account_id": "0123456789abcdef",
    "occurred_at": "2026-06-10T20:00:00Z",
    "recorded_at": "2026-06-10T20:01:00Z",
    "equity": "100.00",
    "cash": "100.00",
    "positions": [],
    "complete": true,
    "phase": "session_close",
    "session_date": "2026-06-10"
  }
]
```

A complete valuation reconciles equity to cash, receivables, liabilities and
position values. Positions need current prices, quote timestamps and values.
Quantity, cost and instrument name can remain unknown. Partial valuations preserve
reported facts without claiming completeness. Buying power never becomes cash.

The existing live snapshot JSON accepts an optional `reporting` valuation. Its
account, timestamp, equity and supplied holdings must match the execution snapshot.
Saving that snapshot also ingests the reporting observation. Existing snapshot
files remain valid. Their absent cash, quantities and flow coverage remain unknown.

## Corrections and linkage

Replay the same ID and content to retry safely. A correction uses a new observation
ID, retains the external event/account/kind, and names the current observation in
`supersedes`. History remains stored. Forked chains, cross-account corrections and
conflicting active valuation instants are rejected. A `voided` correction withdraws
an observation without deleting it. Correct dependent flow references explicitly
when a boundary valuation changes; a stale reference suppresses the return.

External/manual fills use `origin: external` and have no decision link. Agent fills
require a matching decision's mode, account, ticker and side. Each fill records its
actual incremental quantity and notional. An omitted fee means unknown; explicit
zero means confirmed zero. A canceled remainder doesn't erase a partial fill.
`sequence` can preserve an upstream order when events share a timestamp. If that
order isn't known, holding history reports the ambiguity.

Corporate actions record fees, dividends, splits and security transfers. A security
transfer also links its external flow, including the transferred fair value. The
account ledger doesn't infer tax lots or realized gains from missing cost records.

## Exact returns

Coverage observations explicitly attest complete external flows over an interval.
Absence of recorded flows isn't evidence that none occurred. A separate
`activity_complete` attestation supports holding-episode reconciliation.

Each external flow links complete `before_flow` and `after_flow` valuations at its
instant. Their equity difference must equal the signed flow amount. Deposit and
transfer-in amounts are positive; withdrawals and transfer-outs are negative.
Ingest boundary valuations before their flow, and flows before linked transfers.

For example:

| Event | Equity |
| --- | ---: |
| Start | $100 |
| Immediately before deposit | $110 |
| Deposit | $100 |
| Immediately after deposit | $210 |
| End | $231 |

The linked return is `(110 / 100) × (231 / 210) - 1 = 21%`. Investment P&L is
`231 - 100 - 100 = $31`. A deposit-only balance increase produces zero return.
Fees and dividends remain investment results through observed equity. Sparse
snapshots without flow coverage or boundary values don't establish exact returns.
Ordinary endpoints coincident with a flow are withheld when ordering isn't known.

The external-flow and subperiod-linking approach follows the concepts described
in the [GIPS handbook](https://www.gipsstandards.org/standards/gips-standards-for-firms/gips-standards-handbook-for-firms/).
This implementation doesn't claim GIPS compliance.

Daily P&L subtracts external flows from the equity change since the actual previous
NYSE session close. The recorded previous-session date must match the shared
calendar. Missing or contradictory coverage leaves the metric unavailable.

## Publication and display

```powershell
python -m app.public.publication --source data/boustrategy.db --public-db data/boustrategy.public.db --live-profile codex
```

An unfunded account without an execution snapshot can use an explicitly selected
`--live-account-id` instead. Profile changes on the same fingerprint preserve the
same public portfolio. Conflicting account mappings fail publication.

The publisher materializes `1M`, `3M`, `YTD` and `All`. Every range exposes its actual
start/end, requested start and a `Since ...` label. A short history doesn't imply a
full month. The performance endpoint reads these records without source replay:

```text
GET /api/public/v2/portfolios/live/performance*range=All
```

Charts contain at most 400 actual observation timestamps. Sampling preserves the
first/last point and quality-gap transitions. If those markers exceed the bound,
the chart is unavailable rather than concealing gaps. Returns and observed
session-close drawdown use the full eligible series before chart sampling. There's
no inferred intraday history or annualized headline.

QQQ is the primary benchmark; SPY and SMH are optional. Comparisons require exact,
matching session-close dates and positive adjusted-close prices at both endpoints.
Missing endpoints aren't forward-filled. Each benchmark declares its convention.

Holding history distinguishes closed and reopened episodes. The public output
limits episode and fill lists to 100. Costs, cash, fees and quantities remain null
where unknown. Public results exclude account fingerprints, profile IDs and broker
order IDs.

## Existing paper simulations

Publication can reconstruct paper reporting from existing fills and cached closes.
Existing fills remain immutable and receive the additive `legacy_close_v1` label.
New fills use `next_open_v2`: next cached opening prices also value existing holdings
when sizing an order. Missing holding opens wait explicitly. Unaffordable buys fail
without resizing, and settlement or position rebuild rolls back on failure.
Settlement rejects an intent whose fill date precedes already settled history;
chronological resimulation requires a separate, explicit operation. Neither version
simulates fees, slippage, dividends or corporate actions. The original $5,000
simulation balance is the declared baseline. Reconstruction starts with the first
filled intent's creation, not unrelated earlier market history.

Reconstructed timestamps describe simulated sessions. They aren't actual worker
start/completion times. Missing exact-date quotes create valuation gaps. Cached
prices establish the available observation grid; no new prices are fetched.

Legacy fills tied to live or missing intents make paper reporting unavailable.
Persisted positions that disagree with the paper fill ledger are quarantined from
public metrics. Publication doesn't delete or repair those source records. Explicit
reporting ingestion remains available for paper accounts with additional facts.


NYSE session binding uses `nyse-2026-2028-v1`, with explicit coverage from
January 1, 2026 through December 31, 2028. Daily P&L requires the actual previous
eligible session's observed close. Paper valuation timestamps use the calendar's
13:00 ET early close or 16:00 ET regular close. Before close, cached same-day close
prices aren't completed observations. Calendar expiry is an unavailable capability,
not permission to guess a session. FOMC coverage remains separate through 2027,
with 2027 meetings labeled tentative.


Audit additions, September 8, 2026: a previously positive observed balance that becomes
zero is `zero_balance`, rather than `unfunded`. Reconstructed paper benchmarks are
withheld because adjusted-close comparisons include corporate-action effects that the
simulator does not implement. Explicit actual reporting remains separate from simulation.

Each external flow must use its own boundary pair. Consecutive flows at one instant
must connect the previous after-flow equity to the next before-flow equity. Reused
boundaries or unexplained changes suppress linked returns. Financial schema arithmetic
uses sufficient local Decimal precision for the declared quantity and price bounds;
returns exceeding the supported display precision report `return_precision_exceeded`.
