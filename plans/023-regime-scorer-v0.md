# Plan 023: Regime scorer v0 — deterministic GREEN/YELLOW/RED from daily prices

> Executor instructions: follow exactly; verify each step; STOP on
> mismatch. Branch `advisor/023-regime-scorer-v0`, do NOT push, don't
> touch plans/README.md. Never reference any real database path in
> tests.

## Status

- Priority P1. Effort M. Depends on 007 (hard). Planned at local main
  `088c69e`, 2026-07-18.

## Why this matters

The regime model is the sole de-risking mechanism (drawdown doctrine,
`docs/risk_policy.md`) — the acknowledged single point of failure. v0 is
a deterministic, fully-inspectable rule set over index ETF daily bars:
no LLM, no tunable ML, every component visible in every snapshot. That
inspectability IS the design goal; a cleverer model can replace it later
behind the same table.

**Sign-off boundary (read carefully)**: BUILDING and RUNNING this scorer
daily is autonomous-safe — nothing consumes its output yet. The rule
table below is marked REVIEW-REQUIRED: before any decision-generating
run (human checkpoint 5) consumes `regime_snapshots`, the maintainer
must approve the rules, informed by the backtest this plan produces.
Logging a daily track record in the meantime is exactly how the rules
earn that approval.

## Current state (local main `088c69e`)

- `app/prices/cache.py`: `refresh_ticker`, `get_daily_prices` (returns
  bars for a ticker/date range), `latest_bar_date`.
- `app/schemas/decision_record.py`: `RegimeState` enum GREEN/YELLOW/RED
  — reuse it; do not define a second regime enum.
- No `app/regime/`, no `regime_snapshots` table.

## Scope

IN: `app/storage/database.py` (one table), `app/regime/` (create:
`rules.py`, `run.py`), tests.
OUT: consumption by anything (policy already takes `regime_state` from
the record; wiring the snapshot into intake is plan 025), macro/credit
inputs (HYG, breadth, rates — v1 candidates, out), any LLM judgment.

## Design

### Table (append to `_SCHEMA`)

```sql
CREATE TABLE IF NOT EXISTS regime_snapshots (
    snapshot_date TEXT PRIMARY KEY,
    regime TEXT NOT NULL,           -- published (post-hysteresis)
    raw_regime TEXT NOT NULL,       -- what the rules said that day
    score INTEGER NOT NULL,
    components_json TEXT NOT NULL,  -- every component's value + points
    computed_at TEXT NOT NULL
);
```

Append-only: recomputing an existing snapshot_date must produce an
identical row or crash (a changed rule set against an already-published
date is a maintainer event, not a silent overwrite).

### Rule table (REVIEW-REQUIRED — reproduce this banner in rules.py)

Inputs: SPY and QQQ daily closes/volumes, >= 2 years of cached history.

| Component | Rule | Points |
|---|---|---|
| Trend (per index) | close > 200d SMA | +2 / else -2 |
| Trend slope (per index) | 50d SMA > 200d SMA | +1 / else -1 |
| Drawdown (worse of the two) | from 252-session closing high: <5% | +2 |
| | 5-10% | 0 |
| | 10-20% | -2 |
| | >20% | -4 |
| Volatility (SPY) | 20d realized vol (annualized, close-to-close) percentile within trailing 504 sessions: <60th | +1 |
| | 60th-85th | -1 |
| | >85th | -3 |

Score range [-13, +9]. Raw regime: score >= +4 → GREEN; score <= -4 →
RED; else YELLOW.

**Hysteresis**: the published regime changes only after 2 consecutive
sessions with the same raw regime that differs from the current
published one. First-ever snapshot publishes its raw regime directly.
Rationale: a regime that flip-flops daily whipsaws exposure targets;
two-session confirmation is the cheapest stabilizer that keeps RED
reachable within a bad week.

### CLI: `python -m app.regime.run <command> --db PATH`

- `score [--date]` — refresh SPY/QQQ bars (injected seam), compute,
  insert snapshot, print regime + full component breakdown.
- `backtest --start YYYY-MM-DD --end YYYY-MM-DD --out FILE` — compute
  the full daily sequence from CACHED bars only (no snapshots written,
  no network), write markdown: publish-regime timeline, every state
  change with date + score + components, days-per-state summary, and
  the score time series as a table. This file is the maintainer's
  sign-off artifact.

## Steps

1. Table + pure rule functions in `rules.py` (each component a plain
   function returning value + points; tests hit exact boundaries: 5%,
   10%, 20% drawdown; 60th/85th percentiles; SMA crossovers).
2. Hysteresis over synthetic sequences (tests: one-day RED blip does
   not publish; two days does; first-snapshot direct publish).
3. `score` + append-only guard (test: identical recompute is a no-op,
   changed-rules recompute crashes).
4. `backtest` from synthetic bars (assert state-change rows and that no
   snapshots are written).
5. Live prep: fetch 2y SPY+QQQ history via `refresh_ticker` into the
   real db, run `backtest --start <2y ago> --end <today>` and commit
   the report to `docs/research/regime_backtest_v0.md` for maintainer
   review. Then run `score` once for today.
6. Gates: pytest -q, ruff check, ruff format --check, mypy app tests →
   all exit 0; `git status --porcelain` clean after commit.

## STOP conditions

- Fewer than 504 sessions of history obtainable for SPY/QQQ (vol
  percentile is undefined; do not improvise a shorter window).
- You find yourself adding inputs beyond SPY/QQQ bars or points outside
  the table — the rule set is fixed until maintainer review.
- Any test needs the real database or network.
- Current-state signatures don't match local main `088c69e`.

## Maintenance notes

- Maintainer sign-off on the rule table (using the backtest report) is
  part of the checkpoint-5 review; until then snapshots are
  track-record only.
- Daily `score` scheduling: fold into whatever nightly slot runs
  `triggers evaluate` (decided in plan 025's runbook) — not scheduled
  by this plan.
- v1 candidates recorded for later: credit spreads (HYG/LQD), equal-
  weight breadth (RSP vs SPY), and rate shock inputs. Add only with a
  fresh backtest and doc note.
