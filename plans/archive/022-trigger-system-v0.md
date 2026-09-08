# Plan 022: Trigger system v0 — price/volume thresholds, calendar proximity, digest headlines

> Executor instructions: follow exactly; verify each step; STOP on
> mismatch. Branch `advisor/022-trigger-system-v0`, do NOT push, don't
> touch plans/README.md. Never reference any real database path in tests.

## Status

- Priority P2. Effort M. Depends on 007 (hard: price cache), 018 (hard:
  digest headlines), 021 (hard: calendar events + watchlist). Planned at
  local main `460977d`, 2026-07-18.

## Why this matters

Spec §9 as simplified by the 2026-07-15 decision: v0 triggers are
price/volume thresholds, calendar events, and daily-digest flags —
nothing else. The retired 0-20 scoring rubric stays retired.
EXTRAORDINARY_OPPORTUNITY remains a reasoning-layer judgment, not a
trigger type. Triggers are how the future reasoning worker knows what
deserves attention TODAY without re-reading everything; the maintainer's
recorded rationale is that movement thresholds beat cron on
reactivity-per-dollar.

## Current state (local main `460977d`)

- `app/prices/cache.py`: `refresh_ticker(conn, ticker, fetch)` and
  `get_daily_prices`, `latest_bar_date`; daily bars in `daily_prices`.
- Plan 018: `x_route_decisions` rows with `rank = 'headline'`.
- Plan 021: `calendar_events`, `parse_watchlist`.
- No `app/triggers/`, no `trigger_events` table.

## Scope

IN: `app/storage/database.py` (one table), `app/triggers/` (create),
`app/x/run.py` untouched — triggers get their own
`python -m app.triggers.run`, tests.
OUT: any consumption of triggers (that's the reasoning worker, plan
025), notification/alerting, intraday data (daily bars only — a
"price move" here is a close-over-close move detected after the bar
lands, consistent with the no-real-time-data posture).

## Design

### Table (append to `_SCHEMA`)

```sql
CREATE TABLE IF NOT EXISTS trigger_events (
    trigger_id TEXT PRIMARY KEY,     -- deterministic: '<type>:<subject>:<date>'
    trigger_type TEXT NOT NULL,      -- price_move | volume_spike | calendar_upcoming | digest_headline
    subject TEXT NOT NULL,           -- ticker, or post_id for digest_headline
    fired_at TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending'  -- pending | consumed | expired
);
```

Deterministic `trigger_id` makes `evaluate` idempotent: re-running a
date re-derives the same IDs and `INSERT OR IGNORE` keeps first-write
wins (a consumed trigger is never resurrected to pending).

### Thresholds (module constants — these are the tunable dials)

```python
PRICE_MOVE_THRESHOLD = 0.05      # abs 1-day close-over-close return
VOLUME_SPIKE_MULT = 3.0          # vs trailing 20-session average volume
CALENDAR_LOOKAHEAD_DAYS = 3
TRIGGER_TTL_DAYS = 5             # pending older than this -> expired
```

### `python -m app.triggers.run <command> --db PATH`

`evaluate [--date YYYY-MM-DD]` (default: latest available), in order:

1. Refresh daily bars for every watchlist ticker via `refresh_ticker`
   (injected fetch seam for tests, live yfinance in production).
2. `price_move`: for each watchlist ticker with a bar on --date and the
   prior session, fire when abs(close/prev_close - 1) >=
   PRICE_MOVE_THRESHOLD. details: return, closes.
3. `volume_spike`: fire when volume >= VOLUME_SPIKE_MULT × trailing
   20-session average (excluding the day itself; requires >= 20 prior
   bars). details: volume, average, multiple.
4. `calendar_upcoming`: for each calendar_event within
   CALENDAR_LOOKAHEAD_DAYS after --date, fire once (the deterministic
   ID uses the EVENT date as `<date>`, so a 3-day window doesn't fire
   three times). details: event_type, label.
5. `digest_headline`: one trigger per x_route_decisions row with
   rank='headline' decided on --date, subject = post_id. details:
   reason, handle, url.
6. Expire: pending triggers with fired_at older than TRIGGER_TTL_DAYS →
   status 'expired'.
7. Print per-type fired/skipped/expired counts.

`list [--status pending]` — chronological print with details.

`mark --ids ID,ID --status consumed` — the consumption API for plan
025; validates status transitions (pending → consumed|expired only;
anything else crashes).

## Steps

1. Table + deterministic-ID helpers (tests: idempotent re-evaluate,
   consumed never resurrected).
2. price_move + volume_spike over synthetic cached bars (tests: exact
   threshold boundary fires; 19 prior bars does not evaluate volume;
   missing prior bar skips cleanly).
3. calendar_upcoming + digest_headline bridges (tests: window
   single-fire; headline row → trigger; notable row → no trigger).
4. Expiry + `mark` transitions (tests: TTL boundary; illegal transition
   crashes).
5. Gates: pytest -q, ruff check, ruff format --check, mypy app tests →
   all exit 0; `git status --porcelain` clean after commit.

## STOP conditions

- 018 or 021 not merged (both schemas are hard inputs).
- You find yourself adding a trigger type beyond the four (especially
  anything engagement- or crowding-based — both explicitly rejected).
- Any test needs the real database or live network.
- Current-state signatures don't match local main `460977d`.

## Maintenance notes

- Threshold constants are maintainer dials; changing them is a one-line
  commit with rationale, mirroring `MAX_MONTHLY_POST_READS`.
- The digester runbook (019) does NOT run `evaluate` — triggers are
  evaluated by the future reasoning worker's intake (plan 025) or a
  nightly scheduled command; wiring decided there. Nothing schedules
  this plan's code yet.
- When paper positions exist (024), evaluate should union position
  tickers with the watchlist (noted in 024).
