# Plan 026: Dashboard v0 — local read-only visibility over every store

> Executor instructions: follow exactly; verify each step; STOP on
> mismatch. Branch `advisor/026-dashboard-v0`, do NOT push, don't touch
> plans/README.md. Never reference any real database path in tests.

## Status

- Priority P2. Effort M. Depends on 006 (hard); renders 018/021-024
  data where present — every section must degrade gracefully (empty
  table → "none yet" line, missing table → section hidden) so this plan
  can run IN PARALLEL with the 018-025 wave, before or after any of
  them. Planned at local main `088c69e`, 2026-07-18.

## Why this matters

The dashboard is the compensating risk control for the drawdown
doctrine (`docs/risk_policy.md`: a broken regime model "can silently
bleed" until the dashboard exists). It is also how the maintainer
audits an autonomous system by exception. v0 is LOCALHOST-ONLY and
read-only: a private instrument panel. Public hosting, auth, and the
admin roster-editing surface are explicitly out — publishing anything
is a separate maintainer decision with source-policy implications.

## Current state (local main `088c69e`)

- `app/labeling/server.py`: the house pattern — FastAPI, inline-HTML
  render functions, `create_app(db_path)`, `main()` with uvicorn on
  127.0.0.1. Follow it; do not add a template engine or frontend build.
- Stores (existence varies by merge order): decision_records,
  order_intents, status_events, daily_prices, x_runs/x_route_decisions/
  x_article_queue (018), calendar_events (021), trigger_events (022),
  regime_snapshots (023), paper_fills/paper_positions (024), digests as
  files under `data/digests/`.

## Scope

IN: `app/dashboard/` (create: `queries.py`, `server.py`), tests.
OUT: any write endpoint (zero POST routes), auth, public hosting,
roster admin surface, charts libraries (server-rendered HTML tables +
inline SVG sparklines at most), WebSockets/auto-refresh.

## Design

`python -m app.dashboard.server --db PATH [--port 8378]`, bound to
127.0.0.1 explicitly. Pages (GET only):

- `/` overview: paper equity + cash vs STARTING_CASH, current regime +
  score, X reads used/remaining this month, pending triggers count,
  pending articles count, last digest date, counts of decisions by
  final status. Each tile links to its page.
- `/portfolio`: positions table (ticker, shares, avg cost, latest
  close, value, weight, theme, unrealized P/L), fills history, equity
  series as inline SVG sparkline from fills + daily_prices.
- `/decisions`: decision records newest-first — ticker, decision,
  regime, extraordinary flag, final status, policy reasons; each row
  expands to the full status_events trail and record JSON
  (pretty-printed, escaped).
- `/digests`: list `data/digests/*.md` newest-first; render a selected
  file's markdown as escaped preformatted text (no markdown-to-HTML
  dependency in v0).
- `/x`: run ledger, per-account fetched/rank counts (roster READ-ONLY
  view), article queue with status.
- `/regime`: snapshot timeline with score components, state changes
  highlighted.
- `/triggers`: trigger_events by status with details.

X-content rule (source policy): post SNIPPETS (≤ 280 chars, as already
stored in digests) + links are fine on this PRIVATE surface, but build
the render helpers so a future public mode can swap snippets for
claim-summaries-only — one function, one switch, documented inline.

All queries in `queries.py` as plain functions returning dicts/lists
(unit-testable without the server); `server.py` only renders. Missing
tables detected via `sqlite_master`, rendering the section-hidden path.

## Steps

1. `queries.py` with graceful-degradation contract (tests: full
   synthetic db; empty db; partially-migrated db with tables absent).
2. Pages, following the labeling server's HTML conventions; escape
   everything user-content-derived (post text, reasons, JSON).
3. Smoke test via FastAPI TestClient: every route 200s on both an empty
   and a populated synthetic db; zero non-GET routes registered
   (explicit assertion over the app's route table).
4. Gates: pytest -q, ruff check, ruff format --check, mypy app tests →
   all exit 0; `git status --porcelain` clean after commit.

## STOP conditions

- You find yourself adding a POST/mutation route, auth, an external
  frontend dependency, or a non-localhost bind.
- Any test needs the real database.
- Current-state signatures don't match local main `088c69e`.

## Maintenance notes

- The future admin surface (roster editing, maintainer decision
  2026-07-12) goes in a SEPARATE module with explicit auth when
  planned — v0's zero-write guarantee is a tested invariant worth
  keeping pure.
- Public dashboard = new plan: hosting, auth, claim-summary-only X
  rendering, "source deleted" markers. The render-helper switch above
  is its landing point.
- Port 8378 chosen to sit next to the labeling UI's 8377; both can run
  simultaneously.
