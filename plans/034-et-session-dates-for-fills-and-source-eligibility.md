# Plan 034: Use the New York session date, not the UTC date, for paper fills, price refresh, and source eligibility

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 40b317b..HEAD -- app/paper/broker.py app/reason/run.py`
> plus manual comparison for the UNTRACKED files `app/public/publication.py`
> and `app/public/explanations.py` (compare the excerpts below with
> `sed -n '<start>,<end>p' <file>`). On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW (paper/refresh sites) / MED (publication sites: existing projections shift, needs the checkpoint version bump)
- **Depends on**: none. If plan 032 has landed, the checkpoint version will already be 8; bump to 9 in that case (see Step 4).
- **Category**: bug
- **Planned at**: commit `40b317b` (branch `advisor/030-private-dual-agent-dashboard`, working tree uncommitted), 2026-09-08

## Why this matters

The system is rigorously New York-session based: `save_run`, `claim`,
`record_due`, and the exchange calendar all derive "which trading day" from
`astimezone(NEW_YORK).date()`. Four sites instead call `.date()` on a UTC-aware
timestamp, which is the UTC calendar date. From 20:00 ET (EDT) or 19:00 ET (EST)
until midnight ET, the UTC date is already tomorrow. Consequences:

- **Paper fills land one session late.** `_settle` looks for the first daily
  bar with `bar_date > created_at.date()`. An intent authored at 21:00 ET on
  Monday has a UTC date of Tuesday, so the first eligible bar is Wednesday's
  open, silently skipping Tuesday. That changes simulated entry prices and every
  performance number derived from them. The Sunday 18:00 ET weekly slot and the
  17:45 ET close slot are not affected today; a later evening slot, a manual
  evening session, or an event-driven run would be.
- **Price refresh window starts a day late** for the same intents
  (`_pending_intent_dates` uses `substr(created_at, 1, 10)`).
- **Source eligibility is one day too generous.** Publication admits a source as
  corroboration when `published_on <= record.created_at.date()`. For a decision
  created at 21:00 ET Monday, the UTC date is Tuesday, so a source published on
  Tuesday is treated as available to a Monday-evening decision. The same
  comparison exists for thesis reviews.

After this plan every one of these sites uses the ET session date, matching the
rest of the codebase.

## Current state

Files and roles:

- `app/x/calendar.py:6` — `NEW_YORK = ZoneInfo("America/New_York")`, the canonical constant.
- `app/paper/broker.py` — paper broker; `_settle(conn, through_date)` picks the fill bar per pending intent.
- `app/reason/run.py` — session preparation; `_pending_intent_dates` decides from which date to refresh prices for pending paper intents.
- `app/public/publication.py` — the trusted publisher; decision source eligibility at line ~530-536; checkpoint `"version"` at line ~203.
- `app/public/explanations.py` — thesis review source eligibility at line ~226-231.
- `tests/paper/test_paper.py` — exemplar paper tests (`_intent(conn, id, side, weight, created)` helper builds an intent whose `created_at` is `datetime.combine(created, datetime.min.time(), tzinfo=UTC)`; `_bar(ticker, day, open)`; `upsert_daily_prices`).
- `tests/public/test_explanations.py` — has a test around line 317 that registers a source with `published_on="2026-06-11"` against a decision created 2026-06-10 and asserts it is excluded; that is the exemplar for the eligibility tests.

### Excerpt A — `app/paper/broker.py:1-9` (imports) and `:95-105` (fill bar query)

```python
import math
import sqlite3
from datetime import UTC, date, datetime

from app.schemas.order_intent import OrderIntent
from app.storage.records import get_decision_record
from app.storage.runtime import immediate
```

```python
    for (intent_json,) in rows:
        intent = OrderIntent.model_validate_json(intent_json)
        query = """
            SELECT bar_date, open FROM daily_prices
            WHERE ticker = ? AND bar_date > ?
        """
        parameters = [intent.ticker, intent.created_at.date().isoformat()]
        if through_date is not None:
            query += " AND bar_date <= ?"
            parameters.append(through_date.isoformat())
        query += " ORDER BY bar_date LIMIT 1"
```

`OrderIntent.created_at` is `AwareDatetime` (`app/schemas/order_intent.py:30`).

### Excerpt B — `app/reason/run.py:85-92` (price refresh window)

```python
def _pending_intent_dates(conn: sqlite3.Connection) -> dict[str, date]:
    rows = conn.execute(
        """
        SELECT o.ticker, MIN(substr(o.created_at, 1, 10))
        FROM order_intents o
        LEFT JOIN paper_fills f ON f.order_intent_id = o.order_intent_id
        WHERE f.fill_id IS NULL AND o.execution_mode = 'PAPER'
        GROUP BY o.ticker ORDER BY o.ticker
```

`run.py` already imports `NEW_YORK` from `app.x.calendar` (line 37). Stored
`created_at` strings are ISO-8601 with offset (Python `isoformat()` of an aware
datetime, e.g. `2026-06-11T01:00:00+00:00`).

### Excerpt C — `app/public/publication.py:531-536` (decision source eligibility)

```python
                decision_sources = {
                    ref: metadata
                    for ref, metadata in sources.items()
                    if metadata["published_on"] is None
                    or metadata["published_on"] <= record.created_at.date().isoformat()
                }
```

`publication.py` already imports `NEW_YORK` (line 35). `record` is an
`InvestmentDecisionRecord` whose `created_at` is aware.

### Excerpt D — `app/public/explanations.py:226-231` (review source eligibility)

```python
    review_sources = {
        ref: metadata
        for ref, metadata in sources.items()
        if metadata["published_on"] is None
        or metadata["published_on"] <= review.reviewed_at.date().isoformat()
    }
```

Check whether `explanations.py` imports `NEW_YORK`; if not, add
`from app.x.calendar import NEW_YORK`.

### Excerpt E — `app/public/publication.py:201-204` (checkpoint version)

```python
            checkpoint = json.dumps(
                {
                    "version": 7,
```

(It is 8 if plan 032 landed first.)

### Excerpt F — `tests/paper/test_paper.py:64-79` (exemplar)

```python
def test_settle_uses_earliest_bar_after_intent_and_replay_matches(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    _intent(conn, "buy", "BUY", 0.10, date(2026, 7, 20))
    upsert_daily_prices(
        conn,
        [_bar("NVDA", date(2026, 7, 20), 90), _bar("NVDA", date(2026, 7, 21), 100)],
    )

    assert settle(conn) == (1, 0)
    ...
    assert fill == (100.0, "2026-07-21")
```

`_intent` (line 13-35) accepts a `date` and builds `created_at` at UTC midnight.
For this plan's test you need an intent created at a specific aware instant, so
read the helper and either add an optional `created_at: datetime | None`
keyword to it (keep the existing call sites working) or build the record inline
the same way the helper does.

### Repo conventions that apply

- AGENTS.md: crash early; no single-use helpers; comments only for non-obvious business logic (the ET-vs-UTC boundary IS non-obvious — one short comment per site is appropriate).
- Session-day derivation convention: `instant.astimezone(NEW_YORK).date()` (see `app/storage/runtime.py:40`, `app/storage/schedules.py:198`).
- Publication changes that alter existing projections bump the checkpoint version so existing public stores refresh (`docs/plan-031-audit.md`, "Publication checkpoint version 7 forces existing projections to refresh").

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Paper tests | `python -m pytest -q tests/paper tests/reason/test_reason.py` | all pass |
| Public tests | `python -m pytest -q tests/public` | all pass |
| Full tests | `python -m pytest -q` | all pass |
| Lint | `python -m ruff check .` | `All checks passed!` |
| Format | `python -m ruff format --check .` | `N files already formatted` |
| Types | `python -m mypy app tests` | `Success: no issues found` |

## Scope

**In scope**:
- `app/paper/broker.py` (Excerpt A site only)
- `app/reason/run.py` (`_pending_intent_dates` only)
- `app/public/publication.py` (Excerpt C site and the version constant only)
- `app/public/explanations.py` (Excerpt D site only)
- `tests/paper/test_paper.py`, `tests/reason/test_reason.py`, `tests/public/test_explanations.py` (add tests)

**Out of scope**:
- `app/performance/paper.py` — the paper reconstruction replays fills by `fill_date`, which is already a bar date; do not touch.
- Any other `.date()` call. `grep -rn "\.date()" app` returns many legitimate uses on values that are already ET-local or are pure dates; only the four excerpted sites are wrong.
- Existing paper fills in any real database — this plan changes future fills only; no ledger rewrite.
- `docs/reporting.md`, `docs/mandate.md`, `docs/risk_policy.md` — maintainer-owned; no doc changes needed.

## Git workflow

- Branch: `advisor/034-et-session-dates`, from the current working branch. Stage only in-scope paths with `git add <path>`; never `git add -A` (the tree has a large uncommitted delta that is not yours).
- Commit style: `fix: settle paper intents on the ET session date`.
- Do NOT push.

## Steps

### Step 1: Paper fill bar selection

In `app/paper/broker.py` (Excerpt A) change the parameter to
`intent.created_at.astimezone(NEW_YORK).date().isoformat()` and add
`from app.x.calendar import NEW_YORK` to the imports. Add a one-line comment:
the fill must use the first session AFTER the intent's New York session day; the
UTC date is already tomorrow after 20:00 ET.

**Verify**: `python -m pytest -q tests/paper` → existing tests pass.

### Step 2: Paper fill test

In `tests/paper/test_paper.py` add
`test_evening_et_intent_fills_at_next_session_open_not_the_one_after`:

- Arrange: an intent with `created_at = datetime(2026, 7, 21, 1, 30, tzinfo=UTC)` (that is 21:30 ET on Monday 2026-07-20). Bars for `NVDA` on 2026-07-20 (open 90), 2026-07-21 (open 100), 2026-07-22 (open 110).
- Act: `settle(conn)`.
- Assert: fill is `(100.0, "2026-07-21")`.

Run this test once against the unpatched code (temporarily revert Step 1) and
confirm it fails with a fill on `2026-07-22`; then restore Step 1.

**Verify**: `python -m pytest -q tests/paper` → passes including the new test.

### Step 3: Price refresh window

In `app/reason/run.py` `_pending_intent_dates` (Excerpt B): the SQL cannot do
timezone conversion, so select the raw `created_at` strings instead of the
`substr` and compute the minimum ET date in Python:

```python
SELECT o.ticker, o.created_at FROM order_intents o
LEFT JOIN paper_fills f ON f.order_intent_id = o.order_intent_id
WHERE f.fill_id IS NULL AND o.execution_mode = 'PAPER'
```

then build `{ticker: min(datetime.fromisoformat(created).astimezone(NEW_YORK).date(), ...)}`.
Read the rest of the function first to preserve its return type
(`dict[str, date]`) and any subsequent processing of the rows.

Add a direct unit test in `tests/reason/test_reason.py` (no existing test
references `_pending_intent_dates`; write a plain arrange/act/assert function
that connects a `tmp_path` database with `connect`, inserts one PAPER order
intent via the same helper the paper tests use — see `_intent` in
`tests/paper/test_paper.py:13-35` — with `created_at = 2026-07-21T01:30:00+00:00`,
then calls `_pending_intent_dates(conn)`): the returned start date for that
ticker is `date(2026, 7, 20)`.

**Verify**: `python -m pytest -q tests/reason/test_reason.py` → passes.

### Step 4: Publication and review source eligibility

1. In `app/public/publication.py` (Excerpt C) change the comparison to
   `metadata["published_on"] <= record.created_at.astimezone(NEW_YORK).date().isoformat()`.
2. In `app/public/explanations.py` (Excerpt D) change to
   `review.reviewed_at.astimezone(NEW_YORK).date().isoformat()`; add the `NEW_YORK` import if missing.
3. Bump the checkpoint `"version"` by one (7→8, or 8→9 if plan 032 already landed). Check with `grep -n '"version":' app/public/publication.py` first.

Add in `tests/public/test_explanations.py`, modeled on the existing test near
line 317 that uses `source_record(published_on="2026-06-11")`:
`test_source_published_on_the_utc_date_of_an_evening_et_decision_is_not_eligible`
— decision `created_at = 2026-06-11T01:00:00+00:00` (21:00 ET on 06-10), source
`published_on="2026-06-11"`; publish; assert the source does not appear in the
decision's public narrative sources. And a positive control: `published_on="2026-06-10"` IS eligible.

**Verify**: `python -m pytest -q tests/public` → all pass.

### Step 5: Full gates

Run every command in the table; `git status --short` shows only in-scope files.

## Test plan

- `tests/paper/test_paper.py`: evening-ET intent fills at the next session, not the one after.
- `tests/reason/test_reason.py`: refresh window starts on the ET date.
- `tests/public/test_explanations.py`: source dated on the UTC-next-day is not eligible for an evening-ET decision; same-ET-day source is.
- Verification: `python -m pytest -q` → all pass, 3-4 new tests.

## Done criteria

- [ ] `grep -n "created_at.date()" app/paper/broker.py app/public/publication.py` → no matches
- [ ] `grep -n "reviewed_at.date()" app/public/explanations.py` → no matches
- [ ] `grep -n "substr(o.created_at" app/reason/run.py` → no matches
- [ ] checkpoint version incremented by exactly one
- [ ] `python -m pytest -q` exits 0 with the new tests present
- [ ] `python -m ruff check .`, `python -m ruff format --check .`, `python -m mypy app tests` exit 0
- [ ] `git status --short` shows no changes outside the in-scope list
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:

- Any excerpt does not match the live file.
- The Step 2 test does not fail against the unpatched code.
- `_pending_intent_dates` has callers that depend on the SQL shape (e.g. pass extra parameters) — `grep -rn "_pending_intent_dates" app tests`.
- An existing public test fails after Step 4 for a reason other than the version bump forcing a refresh.
- You find a fifth site using a UTC `.date()` for a session decision; report it rather than fixing it here.

## Maintenance notes

- Rule for reviewers: any "which trading day" derivation from an aware timestamp must go through `astimezone(NEW_YORK)`; a bare `.date()` on an aware datetime is a review flag.
- Existing fills in a real database that were settled one session late (if any) are historical facts and stay unchanged; `docs/plan-031-audit.md` already versions paper semantics (`next_open_v2`). If the maintainer wants those repaired, that is a separate, explicit ledger operation.
- Deferred: the eight inline `ZoneInfo("America/New_York")` reconstructions across `app/` (e.g. `app/dashboard/server.py`, `app/x/replay.py`, `app/performance/paper.py`) could all import `NEW_YORK` from `app.x.calendar`; harmless duplication today, worth a mechanical sweep later.
