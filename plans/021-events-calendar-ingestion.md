# Plan 021: Events calendar ingestion — earnings + FOMC, watchlist-seeded

> Executor instructions: follow exactly; verify each step; STOP on
> mismatch. Branch `advisor/021-events-calendar`, do NOT push, don't
> touch plans/README.md. Never reference any real database path in
> tests. Requires web access (FOMC schedule lookup + a live yfinance
> check).

## Status

- Priority P2. Effort S-M. Depends on 004/007 (done); soft on 018 (adds
  a digest section — if 018 is unmerged, deliver the section renderer as
  a standalone function and note it). Planned at local main `460977d`,
  2026-07-18.

## Why this matters

The maintainer's "boring but rock solid" news floor (decision
2026-07-12): the system should never be surprised by a scheduled event.
v0 is deliberately just earnings dates for watchlist tickers plus the
FOMC meeting schedule — cheap, free-source, no human input required to
operate. CPI/jobs and other macro prints are explicitly deferred.

## Current state (local main `460977d`)

- `app/prices/yfinance_source.py`: yfinance is already a dependency.
- `app/x/signals.py` / `x_signals` table: `signal_json` contains a
  `tickers` list per captured signal — the seed source for watchlist
  suggestions.
- `app/x/calendar.py` (plan 018): the static-table +
  `CalendarCoverageError` pattern to copy for the FOMC table.
- No `docs/watchlist.md`, no `app/events/`, no `calendar_events` table.

## Scope

IN: `app/storage/database.py` (one table), `app/events/` (create:
`store.py`, `fetch.py`, `run.py`), `docs/watchlist.md` (create, stub +
suggestions — see below), digest `## Calendar` section (in 018's
renderer), tests.
OUT: macro prints beyond FOMC, holdings-derived tickers (no live
holdings yet; plan 024 adds paper positions — a maintenance note covers
wiring them in later), any UI.

## Design

### Watchlist file — mirrors the roster pattern

`docs/watchlist.md` is maintainer-curated. Format: `- TICKER — one-line
reason` for approved entries; `* TICKER — reason` for suggestions the
parser ignores. The executor creates the file containing: a header
explaining the format + curation rule (maintainer-only approval, same
doctrine as the X roster), zero approved entries, and one `*` suggestion
line per distinct ticker found in `x_signals.signal_json` tickers
(sorted by frequency, reason = "appeared in N captured signals").
The maintainer flips `*` to `-` to approve. Parser
`parse_watchlist(path) -> list[str]` reads only `-` lines, validates
ticker shape (`^[A-Z.]{1,12}$`), crashes early on a malformed approved
line.

### Table (append to `_SCHEMA`)

```sql
CREATE TABLE IF NOT EXISTS calendar_events (
    event_type TEXT NOT NULL,         -- earnings | fomc
    ticker TEXT NOT NULL DEFAULT '',  -- '' for fomc
    event_date TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',   -- e.g. 'FOMC meeting day 2', 'estimated'
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (event_type, ticker, event_date)
);
```

This table is a refreshable CACHE (like `daily_prices`), not a judgment
record — the append-only doctrine does not apply. `refresh` deletes
future-dated earnings rows for a ticker before inserting current dates,
so a moved earnings date never leaves a stale ghost. FOMC rows are
replaced wholesale from the static table. Past-dated rows are never
touched (they are the historical record capsules replay against).

### FOMC static table

In `app/events/fetch.py`, same coverage pattern as `app/x/calendar.py`:
explicit `FOMC_COVERAGE_END`; requesting sync beyond it raises. Populate
meeting dates through end-2026 from federalreserve.gov (STOP if you
cannot reach it — do not populate from memory). Cross-check hint, to
verify not copy: remaining 2026 meetings are expected to be late July,
mid September, late October, and early December (two days each).

### Earnings via yfinance

`fetch_earnings_dates(ticker) -> list[date]` using
`yf.Ticker(t).get_earnings_dates` — future dates only, labeled
`estimated` (yfinance earnings dates are estimates until confirmed).
Injected-fetcher seam exactly like plan 007's price source so tests
never hit the network. STOP if the yfinance API surface has drifted from
this method name.

### CLI: `python -m app.events.run <command> --db PATH`

- `refresh` — parse watchlist; fetch earnings per approved ticker; sync
  FOMC; print per-ticker counts and a `watchlist empty — approve
  tickers in docs/watchlist.md` notice when applicable. Zero approved
  tickers is a valid state, not an error.
- `upcoming [--days 14]` — print chronological upcoming events.

### Digest integration

`## Calendar` section in 018's `digest-render`, between `## Article
queue` and `## Synthesis`: events in the next 7 calendar days, one line
each; omitted entirely when empty.

## Steps

1. Table + watchlist parser + `docs/watchlist.md` generation (tests:
   `*` ignored, malformed approved line crashes, suggestion generation
   from synthetic x_signals rows).
2. FOMC static table + sync (test: replace-wholesale; coverage error).
3. Earnings fetch with injected fetcher (tests: refresh replaces future
   rows only; past rows untouched).
4. `upcoming` + digest section (test: 7-day window, empty omission).
5. One LIVE check (like plan 007): `refresh` against a temp db with a
   one-ticker watchlist (use NVDA), report what came back in the plan
   row / final report. Delete the temp db.
6. Gates: pytest -q, ruff check, ruff format --check, mypy app tests →
   all exit 0; `git status --porcelain` clean after commit.

## STOP conditions

- No web access, or federalreserve.gov unreachable (FOMC table must
  come from the primary source).
- yfinance earnings API surface differs from the design.
- Current-state signatures don't match local main `460977d`.

## Maintenance notes

- Maintainer: approve watchlist tickers (flip `*` → `-`) — the calendar
  is empty until then. This is the same 5-minute curation duty as the
  roster, not a new labeling burden.
- When plan 024 lands, `refresh` should also union in paper-position
  tickers (one-line change; noted there too).
- FOMC coverage must be extended when the Fed publishes the next year's
  schedule; the coverage error is the tripwire.
