# Plan 042: Use Robinhood where only the broker knows, and direct APIs for market data

## Status

- **Priority**: P2 · **Effort**: L overall, delivered in independent phases (S-M each)
- **Risk**: LOW for read-only phases, MEDIUM for anything that changes account state
- **Depends on**: none. Phase 3 (alerts) pairs with plan 041.
- **Planned at**: `cea247a` plus uncommitted dashboard changes, 2026-09-15; revised the same day
- **Build**: not yet. Explore and decide phase by phase (maintainer, 2026-09-15).

## Why

The bot uses 8 of the 74 tools the `robinhood-trading` MCP server exposes: `get_accounts`,
`get_portfolio`, `get_equity_positions`, `get_equity_quotes`, `get_equity_tradability`,
`get_equity_orders`, `review_equity_order` and `place_equity_order`. The full inventory was
captured on 2026-09-15 by a read-only probe (see "Discovery"). **No tool exposes deposits,
withdrawals or transfers.**

## The deciding constraint

This harness can reach Robinhood **only through a Codex AI session**; there is no direct API. So
every Robinhood read costs a model session (tokens and tens of seconds), is bounded by MCP
reliability, and returns numbers a model transcribed into JSON rather than numbers code fetched.
That's acceptable where Robinhood is the only source of the truth. It's the wrong trade for bulk
market data, where the goal is deterministic, verifiable input and free direct APIs exist.

**Rule: use Robinhood only for facts only the broker has, or actions only the broker can take.
Get market data from direct APIs through ordinary code.**

| Need | Source | Why |
|---|---|---|
| Account, positions, orders, execution | Robinhood (today) | Only the broker knows |
| Price alerts between reviews | Robinhood | Robinhood monitors prices itself; no polling |
| Stale order cancellation | Robinhood | Only the broker can cancel |
| Tax lots, realized P&L | Robinhood | Only the broker has lot-level truth |
| Watchlists visible in the app | Robinhood | Only visible there |
| Candidate scans | Robinhood (maybe) | Saved scanners with live filters; weigh against a code screen |
| Daily prices, benchmarks | Direct API (Massive/Polygon) | Bulk, deterministic; plans/README already names Massive as the yfinance replacement |
| SEC filings and XBRL facts | SEC EDGAR API | Free, primary source, deterministic |
| Fundamentals, earnings dates | Direct API or EDGAR | Bulk and deterministic |
| Quotes for intake and reference prices | Direct API | One call per ticker in code, not a model session |

The market-data rows are out of scope here. They belong in a separate plan (a future 043,
"deterministic market data"), which the research-first memory already lists as a later plan.

## Invariants

- The review authoring session never gets the broker MCP (plan 040).
- Only the execution session pre-approves tools, and today only `review_equity_order` and
  `place_equity_order` (`app/broker/session.py`, `approved_tools`). Any new state-changing tool is
  approved per session, by name, and never in a collector or read-only session.
- Options, crypto, exercise and margin-upgrade tools stay out of scope (mandate: long-only U.S.
  equities and ETFs).
- Every broker session output is schema-validated JSON with a session log under
  `data/logs/broker/`, like today's collector.
- The database stays the source of truth; broker-side state (alerts, watchlists) is a mirror
  rebuilt from it.

## Discovery (do first, before any phase)

Tool names are known, but argument and response shapes are not. For each tool a phase uses, run a
read-only Codex session under the bot identity that calls it once and saves the raw response to
`data/broker/probes/<tool>.json`. For state-changing tools, probe only the read side (for example
`get_alerts`, `get_watchlists`) and design the write from the maintainer-watched first run. Write
Pydantic models from real output. Lesson from plan 038: review accepted fractional limit orders
that placement rejected.

Tool-list probe that produced the inventory (the maintainer ran it; Claude's permission rules block
starting bot sessions):

```powershell
$env:CODEX_HOME = "$HOME\.codex-boustrategy"
codex exec --sandbox read-only --skip-git-repo-check --ephemeral --color never -m gpt-5.6-luna -c mcp_servers.robinhood-trading.enabled=true "List the exact name of every tool the robinhood-trading MCP server exposes, one per line, with a one-sentence description. Do not call any tool."
```

## Phases

Each phase is independently useful and can be approved, built or dropped on its own.

### Phase 1: Execution hygiene (state-changing, small)

- **Tools**: `cancel_equity_order`, with `get_equity_orders` (already used).
- **Why**: an order still open after the executor's five-minute reconcile stays `SUBMITTED`
  (`docs/execution/EXECUTOR.md`), and intents expire at the session close. Nothing cancels a bot
  order left working at the broker.
- **Shape**: a close-of-session sweep that lists open bot orders, cancels any whose intent has
  expired, and appends `CANCELED` lifecycle events. `cancel_equity_order` is approved only in that
  sweep session.

### Phase 2: Portfolio accuracy (read-only)

- **Tools**: `get_equity_tax_lots`, `get_pnl_trade_history`, `get_realized_pnl`.
- **Why**: holding episodes show `activity_coverage_missing`, and there's no realized P&L source for
  when sells begin.
- **Shape**: the valuation collector (already a Robinhood session every 15 minutes) adds per-lot
  cost basis to snapshots, so no new session is needed. A daily read of realized P&L cross-checks
  the performance report, which flags disagreements rather than replacing its own computation.

### Phase 3: Price alerts between reviews (state-changing)

- **Tools**: `create_alert`, `update_alert`, `delete_alert`, `get_alerts`, `get_alert_log`,
  `mark_alerts_read`.
- **Why**: reviews run four times a session. Plan 041 needs short-call removal conditions
  (`cover_below`, `stop_above`) watched reliably, and holdings have invalidation criteria with
  nothing watching price levels between reviews.
- **Shape**:
  - A reconciler keeps one Robinhood alert per numeric condition (short-call cover and stop, and an
    optional holding stop level), creating, updating and deleting alerts to match the database.
  - The prepare step reads `get_alert_log`, turns fired alerts into a new `price_alert` trigger type
    in `app/triggers/`, and marks them read.
  - Alerts are signals for the next review; they never place or cancel orders.
- **Approval**: a dedicated alert session pre-approves only the alert tools.
- **Maintainer decision**: whether holdings get alert levels, and who sets them (review
  invalidation criteria are prose today).

### Phase 4: Watchlists visible in the app (state-changing, optional)

- **Tools**: `get_watchlists`, `create_watchlist`, `add_to_watchlist`, `remove_from_watchlist`,
  `get_watchlist_items`.
- **Shape**: mirror WATCHLIST and SHORT_WATCHLIST decisions into two Robinhood watchlists ("Bou
  watchlist", "Bou shorts"), rebuilt from the database when decisions change, so the maintainer
  sees them in the Robinhood app.

### Phase 5: Candidate scans (evaluate before building)

- **Tools**: `get_scanner_filter_specs`, `create_scan`, `update_scan_filters`, `run_scan`,
  `get_scans`.
- **Why**: every review must research three candidates (plan 040), but candidates come only from
  holdings, digests and triggers. Plan 040 deferred an intake candidate list.
- **Evaluate first**: once the market-data plan gives the harness daily prices and volume, a
  deterministic screen in code (momentum, unusual volume, 52-week highs within the themes) may
  replace this for free. Build this phase only if Robinhood's scanner filters offer something a
  code screen can't.
- **Shape if built**: the maintainer defines a few saved scans once, from an operator command. The
  prepare step runs them read-only and adds results as leads labeled as scan output, not evidence.

## Deliberately not using Robinhood for

- `get_equity_historicals`, `get_index_historicals`, `get_index_quotes`: use a direct price API
  (future plan 043).
- `get_sec_filing`, `get_sec_filing_index`, `get_sec_filing_facts`, `get_sec_filing_facts_catalog`,
  `get_financials`, `get_equity_fundamentals`: use SEC EDGAR directly (future plan 043).
- `get_earnings_calendar`, `get_earnings_results`: use a direct source (future plan 043).
- `get_equity_quotes` for intake or reference prices: a direct quote API. Execution preflight keeps
  using the broker quote, because placement is checked against it.
- `get_equity_news`, `get_equity_technical_indicators`, `search`: low value relative to a model
  session each. Technical indicators can be computed from direct price data.
- Every option, crypto, exercise and upgrade tool: out of mandate.

## Maintainer decisions

1. **External cash flows (decided 2026-09-15)**: no automatic cash reconciliation. The public return
   uses maintainer-reported contributed capital (`ContributedCapital` in `ops/public.local.psd1`,
   $100 as of 2026-09-15), updated when the maintainer adds or withdraws cash.
2. **Phase order.** Proposed: Discovery → 1 (small, removes a real execution gap) → 2 → 3 alongside
   plan 041 → 4 → 5 only after plan 043.
3. **Phase 3**: holding alert levels, and who sets them.
4. **Plan 043**: whether to write the deterministic market-data plan now.

## Verification (per phase)

- Pydantic models are built from the discovery probe's recorded responses, with a test fixture
  taken from that real output.
- `python -m pytest -q`, `ruff check`, `ruff format --check`, `mypy app tests`, and `npm test`
  when the UI changes.
- A dry run on a scratchpad copy of `data/boustrategy.db` before touching the live database.
- For state-changing phases, a first run watched by the maintainer. Restart the long-running
  publisher and server if schemas changed.
