# Plan 024: Paper broker — simulated fills, positions, and the real PortfolioContext

> Executor instructions: follow exactly; verify each step; STOP on
> mismatch. Branch `advisor/024-paper-broker`, do NOT push, don't touch
> plans/README.md. Never reference any real database path in tests.

## Status

- Priority P1. Effort M. Depends on 005/006/007/009 (done). Independent
  of 018-023 (may run in parallel with them). Planned at local main
  `088c69e`, 2026-07-18.

## Why this matters

Order intents currently dead-end at CREATED — nothing fills them, so
there are no positions, no equity, and `PortfolioContext` (which the
policy gate needs for quotas/holdings/theme caps) has no real producer.
Paper trading is Phase 1's endpoint and the evidence engine for every
posture unlock the maintainer approved on 2026-07-18 (frequency changes
come from paper-capsule results, never agent self-belief). This is pure
simulation; the live broker adapter remains Phase 2, human checkpoint 6.

## Current state (local main `088c69e`)

- `app/schemas/order_intent.py`: `OrderIntent` (order_intent_id,
  decision_id, ticker, side BUY|SELL, order_type, `target_weight`
  0..1, status enum with only CREATED).
- `app/state/pipeline.py`: `process_decision` persists records, runs
  policy, creates intents; takes `PortfolioContext | None`.
- `app/policy/decision_policy.py`: `PortfolioContext(holdings_count,
  buy_add_trades_today, sell_trim_trades_today,
  primary_theme_weights)`; the theme-weights comment says weights
  EXCLUDE the evaluated ticker.
- `app/storage/records.py`: `get_decision_record` (source of
  `primary_theme_id` per decision), `save_order_intent`.
- `app/prices/cache.py`: `get_daily_prices`, `latest_bar_date`.
- No fills/positions tables, no `app/paper/`.

## Scope

IN: `app/storage/database.py` (two tables), `app/paper/` (create:
`broker.py`, `context.py`, `run.py`), tests.
OUT: live brokerage anything, intraday fills, commissions/slippage
modeling (v0 fills at the open, frictionless — note it in reports),
changes to `OrderIntentStatus` (filled-ness is derived from the fills
table by join; the enum stays untouched to avoid schema churn).

## Design

### Tables (append to `_SCHEMA`)

```sql
CREATE TABLE IF NOT EXISTS paper_fills (
    fill_id TEXT PRIMARY KEY,            -- 'fill_<order_intent_id>'
    order_intent_id TEXT NOT NULL UNIQUE,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    shares REAL NOT NULL,
    price REAL NOT NULL,
    fill_date TEXT NOT NULL,             -- the bar date used
    filled_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_positions (
    ticker TEXT PRIMARY KEY,
    shares REAL NOT NULL,
    avg_cost REAL NOT NULL,
    opened_at TEXT NOT NULL,
    primary_theme_id TEXT NOT NULL DEFAULT ''
);
```

`paper_fills` is append-only (UNIQUE intent = at most one fill, ever).
`paper_positions` is derived state, rebuildable from fills — provide
`rebuild_positions(conn)` that replays all fills from scratch; `settle`
uses incremental updates but a test must assert replay ≡ incremental.

Cash is derived, never stored: `STARTING_CASH = 100_000.0`; cash =
STARTING_CASH − Σ(buy fills value) + Σ(sell fills value). Equity = cash
+ Σ(position shares × latest cached close).

### Fill simulation (`settle`)

Deterministic and wall-clock-free: for each unfilled order intent, find
the EARLIEST cached daily bar for its ticker with bar_date strictly
after date(created_at). If none exists yet, report "awaiting bar" and
skip. Fill at that bar's OPEN:

- Compute equity as of that bar date (cash from prior fills + positions
  at that date's closes; a missing close for a held ticker on that date
  → crash early, refresh prices first).
- `delta_value = target_weight × equity − current_position_value`
  (current value at the fill bar's open). BUY-side intent requires
  delta_value > 0, SELL-side requires < 0 — a sign mismatch crashes
  (the intent was computed against a stale portfolio; a human should
  look).
- `shares = |delta_value| / open_price` (fractional shares fine —
  paper). SELL shares are capped at held shares; `target_weight = 0`
  SELL closes the position exactly.
- Update `paper_positions` (weighted avg_cost on buys; position row
  deleted when shares < 1e-9); `primary_theme_id` copied from the
  originating decision record on open.

### The real PortfolioContext (`context.py`)

`portfolio_context(conn, on_date, exclude_ticker=None) ->
PortfolioContext`:

- `holdings_count` = open positions count.
- `buy_add_trades_today` / `sell_trim_trades_today` = order INTENTS
  created on on_date by side (BUY side / SELL side). Quotas count
  decisions made today, not fills — fills land next open by design and
  must not let a burst of same-day decisions under-count.
- `primary_theme_weights` = per-theme position value ÷ equity, at
  latest cached closes, EXCLUDING exclude_ticker (matches the policy
  comment; callers pass the evaluated record's ticker).

### CLI: `python -m app.paper.run <command> --db PATH`

- `settle` — run fill simulation over all unfilled intents; print
  fills/awaiting/skips.
- `positions` — table: ticker, shares, avg_cost, latest close, value,
  weight, theme, unrealized P/L.
- `equity` — cash, positions value, total, vs STARTING_CASH.

## Steps

1. Tables + fills replay (tests: replay ≡ incremental; append-only
   UNIQUE enforced).
2. `settle` (tests: earliest-bar-after selection; awaiting-bar skip;
   sign-mismatch crash; SELL cap; close-to-zero deletes row; avg_cost
   math; equity computed at fill date not today).
3. `portfolio_context` (tests: intent-counting by created date + side;
   exclude_ticker; weights sum sanity).
4. CLI + gates: pytest -q, ruff check, ruff format --check, mypy app
   tests → all exit 0; `git status --porcelain` clean after commit.

## STOP conditions

- You find yourself importing anything broker/HTTP-related — this plan
  is arithmetic over the local database only.
- The `OrderIntent` or `PortfolioContext` shapes differ from Current
  state.
- Any test needs the real database.
- Current-state signatures don't match local main `088c69e`.

## Maintenance notes

- Wire-ins deferred to keep this plan closed: plan 021's `refresh`
  and plan 022's `evaluate` should union position tickers with the
  watchlist (one-liners; do them in plan 025's integration step).
- Frictionless fills slightly flatter results; if paper results ever
  gate a live-money decision, add slippage modeling FIRST.
- `rebuild_positions` is the crash-recovery story: fills are truth,
  positions are cache.
