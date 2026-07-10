# Plan 007: Build the daily OHLCV price cache (yfinance source, SQLite storage)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat e869d55..HEAD -- app/ tests/ pyproject.toml`
> Compare the "Current state" excerpts below against the live code before
> proceeding; on a mismatch, STOP. Assumes **plan 006 has landed**
> (`app/storage/database.py` exists and owns table DDL).

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: LOW-MED (adds the first third-party data dependency; network
  variability is contained to one module and one optional live check)
- **Depends on**: plans/006 (storage helper)
- **Category**: direction
- **Planned at**: commit `e869d55`, 2026-07-10

## Why this matters

Regime scoring (QQQ/SPY/SMH trends), price/volume triggers, thesis price
summaries, and the dashboard all need historical daily prices. The spec
(§6) decides the shape: daily OHLCV is sufficient for v0.1, cached locally,
refreshed after market close and on demand; primary source `yfinance`, free.
Fields to store, per spec: date, open, high, low, close, adjusted close,
volume, source, fetched_at.

Design decisions made here (executor should not revisit): prices live in the
same SQLite database as records, in their own table; the network fetcher is
a separate module injected into the refresh function, so everything except
the fetcher itself is testable offline and alternative sources (Stooq,
Alpha Vantage — the spec's named fallbacks) can be added later without
touching cache logic.

## Current state

- `app/storage/database.py` (from plan 006) — `connect(db_path)` runs a
  `_SCHEMA` executescript; table DDL is centralized in that module by
  design. You will extend `_SCHEMA`.
- `app/schemas/` — pydantic conventions: `ConfigDict(extra="forbid")`,
  `StrEnum`, `AwareDatetime`.
- `pyproject.toml` `[project.dependencies]` currently: `pydantic>=2.0` only.
- No `app/prices/` package exists.

Repo conventions: crash early; plain functions over class hierarchies;
"why" comments only; tests mirror `app/` layout.

## Commands you will need

| Purpose | Command                           | Expected on success |
|---------|-----------------------------------|---------------------|
| Install | `python -m pip install -e .[dev]` | exit 0              |
| Tests   | `python -m pytest -q`             | all pass, exit 0    |
| Lint*   | `python -m ruff check .`          | exit 0              |
| Types*  | `python -m mypy app tests`        | exit 0 (see step 5 note) |

*Only if plan 004 has landed.

## Scope

**In scope** (create/modify only these):

- `pyproject.toml` (add `yfinance>=0.2` to `[project.dependencies]`)
- `app/storage/database.py` (extend `_SCHEMA` with the prices table only)
- `app/prices/__init__.py` (create, empty)
- `app/prices/cache.py` (create)
- `app/prices/yfinance_source.py` (create)
- `tests/prices/__init__.py` (create, empty)
- `tests/prices/test_cache.py` (create)

**Out of scope** (do NOT touch):

- Regime scoring, triggers, indicators — this plan stores and serves bars,
  nothing derives meaning from them.
- Intraday data, non-daily granularity, alternative sources (fallbacks are
  a follow-up once yfinance reliability is observed).
- Scheduling/automation of the after-close refresh (state-machine work).

## Git workflow

- Branch: `advisor/007-daily-price-cache`
- Commit style: short lowercase imperative summary, matching existing history.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: PriceBar model and prices table

Create `app/prices/cache.py` starting with the model:

```python
from datetime import date

from pydantic import AwareDatetime, BaseModel, ConfigDict


class PriceBar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    bar_date: date
    open: float
    high: float
    low: float
    close: float
    adj_close: float | None
    volume: int
    source: str
    fetched_at: AwareDatetime
```

Extend `_SCHEMA` in `app/storage/database.py` with:

```sql
CREATE TABLE IF NOT EXISTS daily_prices (
    ticker TEXT NOT NULL,
    bar_date TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    adj_close REAL,
    volume INTEGER NOT NULL,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (ticker, bar_date)
);
```

**Verify**: `python -c "from app.storage.database import connect; c = connect(':memory:'); c.execute('SELECT * FROM daily_prices')"` → exit 0.

### Step 2: Cache functions

In `app/prices/cache.py`, add plain functions:

```python
def upsert_daily_prices(conn, bars: list[PriceBar]) -> int: ...
def get_daily_prices(conn, ticker: str, start: date | None = None, end: date | None = None) -> list[PriceBar]: ...
def latest_bar_date(conn, ticker: str) -> date | None: ...
```

- `upsert_daily_prices` uses `INSERT OR REPLACE` keyed on
  `(ticker, bar_date)` and returns the number of bars written. Re-fetching
  the same day overwrites silently — price rows are cache, not audit
  records, so unlike plan 006's append-only rule, replacement is correct
  here (sources restate adjusted closes after splits/dividends).
- `get_daily_prices` returns bars ordered by `bar_date` ascending, filtered
  by the optional date range.

**Verify**: `python -m pytest -q` → existing tests still pass.

### Step 3: The yfinance fetcher

Create `app/prices/yfinance_source.py`:

```python
def fetch_daily_bars(ticker: str, start: date, end: date) -> list[PriceBar]: ...
```

Implementation: `yfinance.Ticker(ticker).history(start=..., end=...,
interval="1d", auto_adjust=False)`, mapping rows to `PriceBar` with
`source="yfinance"` and `fetched_at=datetime.now(UTC)`. Skip rows with NaN
close. This module is the ONLY place that imports yfinance.

### Step 4: Refresh with injected fetcher

In `app/prices/cache.py`:

```python
def refresh_ticker(conn, ticker: str, start: date, end: date, fetch=fetch_daily_bars) -> int:
    return upsert_daily_prices(conn, fetch(ticker, start, end))
```

(Import the default fetcher lazily inside the function if a module-level
import would make offline test collection import yfinance eagerly and slow
things down; either is acceptable, note which you chose.)

**Verify (offline)**: `python -m pytest tests/prices -q` → passes using the
fake fetcher (Test plan below).

**Verify (live, once)**: `python -c "from datetime import date; from app.storage.database import connect; from app.prices.cache import refresh_ticker; c = connect(':memory:'); n = refresh_ticker(c, 'QQQ', date(2026, 6, 1), date(2026, 6, 30)); print(n); assert n > 15"` → prints ~20 (trading days in June 2026). Requires network; see STOP conditions if it fails.

### Step 5: Add the dependency and reinstall

Add `yfinance>=0.2` to `[project.dependencies]` in `pyproject.toml`, then
`python -m pip install -e .[dev]`.

If plan 004's mypy gate is active and yfinance lacks type stubs, add the
narrowest possible override in `pyproject.toml`:

```toml
[[tool.mypy.overrides]]
module = "yfinance.*"
ignore_missing_imports = true
```

**Verify**: `python -m pip show yfinance` → exit 0.

## Test plan

In `tests/prices/test_cache.py`, all offline via `connect(":memory:")` and a
fake fetcher (a plain function returning hand-built `PriceBar` lists):

1. `test_upsert_and_get_round_trip` — 3 bars in, same 3 out, ascending
   date order.
2. `test_upsert_same_day_replaces` — upsert a bar for a date, upsert a
   modified bar for the same date, only the new values remain and row count
   for the ticker is 1.
3. `test_get_with_date_range_filters` — 5 bars, range selects the middle 3.
4. `test_latest_bar_date` — returns the max date; `None` for an unknown
   ticker.
5. `test_refresh_ticker_uses_injected_fetcher` — `refresh_ticker(conn,
   "QQQ", start, end, fetch=fake_fetch)` writes exactly the fake's bars and
   returns their count; the fake asserts it was called with the same
   ticker/start/end.
6. `test_bars_for_different_tickers_do_not_collide` — same dates, two
   tickers, both retrievable independently.

No live-network test is committed; the live check is the one-off command in
step 4.

Verification: `python -m pytest -q` → all pass, 6 new tests included.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `python -m pytest -q` exits 0 with no network access; 6 new tests in `tests/prices/`
- [ ] `grep -n "yfinance" pyproject.toml` → one dependency line (plus the mypy override if needed)
- [ ] `grep -rln "import yfinance" app/` → only `app/prices/yfinance_source.py`
- [ ] The live one-off check in step 4 succeeded once (paste its output in your report)
- [ ] If plan 004 landed: `python -m ruff check .` and `python -m mypy app tests` exit 0
- [ ] `git status --porcelain` shows only the seven in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `app/storage/database.py` does not exist (plan 006 has not landed).
- The live check fails after 2 attempts (network blocked, yfinance API
  changed, or rate-limited): finish the offline work, mark the live check
  as NOT RUN in your report, and set the plan status to DONE-EXCEPT-LIVE so
  a human can run it — do not stub or fake the live verification.
- yfinance's return shape doesn't match the mapping in step 3 (the library
  changes periodically) — report the actual columns you received.
- You are tempted to add retry/backoff/scheduling logic — that belongs to
  the state-machine phase.

## Maintenance notes

- The injected-fetcher seam is where Stooq/Alpha Vantage fallbacks (spec
  §6) attach later: same `PriceBar` out, different module, and a wrapper
  that tries sources in order.
- `INSERT OR REPLACE` on `(ticker, bar_date)` means re-running a refresh is
  always safe; the after-close scheduler can be dumb.
- yfinance is an unofficial API and periodically breaks; when the reliance
  becomes operational (live trading), revisit the spec's paid-data
  threshold ("paid historical data should wait until free data blocks
  reliability").
- Plan 008's research report covers alternative/additional market data
  providers; if a provider with an official free tier is adopted, it enters
  through the fetcher seam.
