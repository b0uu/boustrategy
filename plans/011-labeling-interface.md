# Plan 011: Local labeling interface — button-click review for the X trial inbox

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> a STOP condition occurs, stop and report — do not improvise. When done,
> update this plan's status row in `plans/README.md` — unless a reviewer
> dispatched you and told you they maintain the index.
>
> **Drift check (run first)**: `git diff --stat 12abfcc..HEAD -- app/ tests/ pyproject.toml`
> Compare "Current state" excerpts against live code; on mismatch, STOP.
> Requires plans 001-010 landed (all DONE on main at `12abfcc`).

## Status

- **Priority**: P1 (the monitored X trial's ergonomics depend on it)
- **Effort**: M
- **Depends on**: 010 (reviews the inbox 010 fetches)
- **Category**: dx
- **Planned at**: commit `12abfcc`, 2026-07-12

## Why this matters

The monitored X trial (plan 010) makes the maintainer review every fetched
post; the CLI `review` loop requires typing eight fields per capture,
including free-text theme IDs where one typo silently fragments the labeled
dataset. Maintainer decision (2026-07-12): replace the daily driver with a
minimal local web inbox — one post at a time, skip/capture as button
clicks, enums as radio buttons, themes as a fixed button set. Faster labels,
zero typo surface, and the seed of the project's eventual human-judgment
surface.

Scope discipline (maintainer's own anti-slop rule): this is a POST-REVIEW
INBOX, not a dashboard and not a generalized question engine. One page, one
queue. It must be a thin skin over the already-tested functions in
`app/x/posts.py` and `app/x/signals.py` — if you find yourself writing new
business logic, stop and re-read the scope.

**Privacy constraint (hard)**: the page displays full post text, which is
the project's PRIVATE archive (never published, per
`docs/source_policy.md`). The server binds to `127.0.0.1` only. No auth is
added BECAUSE it is loopback-only; do not add network exposure of any kind.

## Current state

- `app/x/posts.py` — `unreviewed_posts(conn, limit=50) -> list[XPost]`
  (oldest first), `mark_reviewed(conn, post_id, review_status)`
  (`unreviewed -> captured|skipped` only, else ValueError),
  `reads_remaining(conn)`, `MAX_MONTHLY_POST_READS = 4000`.
- `app/x/signals.py` — `CapturedSignal` (pydantic, extra="forbid"; fields:
  entry_id, post_id, captured_at, post_url, handle, posted_at,
  primary_theme_id, tickers, claim, claim_type, stance, horizon,
  scrutiny_verdict, why_it_matters) with StrEnums `ClaimType`, `Stance`,
  `Horizon`, `ScrutinyVerdict`; `save_signal(conn, signal)` (idempotent,
  marks the post captured).
- `app/x/run.py` — CLI with `_cmd_review` (the loop this UI supersedes for
  daily use; leave the CLI intact as fallback).
- `app/storage/database.py` — `connect(db_path)`.
- `pyproject.toml` — deps: pydantic, yfinance, httpx. Gates: ruff check,
  ruff format --check, mypy strict on app+tests (all must stay green).
- Conventions (`AGENTS.md`): crash early, no premature abstractions,
  "why" comments only, tests mirror app/ layout.

## Design decisions (made; do not revisit)

- **Stack**: FastAPI + uvicorn. FastAPI because the request/response models
  are pydantic like everything else and mypy checks them; uvicorn as the
  local server. No JS framework, no build step: one server-rendered HTML
  page with vanilla JS `fetch` calls and keyboard shortcuts.
- **Themes as a UI constant**: the 14 theme ids from the spec's taxonomy,
  hardcoded as a module constant in the server (the schema field stays a
  free string — constraining it is a schema decision for later; the buttons
  are what remove the typo risk):
  `ai_semiconductors, ai_infrastructure, ai_bottlenecks, data_centers,
  power_grid_electrification, financial_technology, cloud_hyperscalers,
  networking_interconnect, robotics_automation, cybersecurity, ai_software,
  broad_risk_on_tech, macro_liquidity, emergent_theme`.
- Port 8377, loopback only.

## Scope

**In scope** (create/modify only these):

- `pyproject.toml` (add `fastapi>=0.111`, `uvicorn>=0.30`; narrow mypy
  overrides only if stubs are missing)
- `app/labeling/__init__.py`, `app/labeling/server.py` (create)
- `tests/labeling/__init__.py`, `tests/labeling/test_server.py` (create)

**Out of scope**: any change to `app/x/`, `app/storage/`, schemas, or
policy; account-graph editing; charts/stats pages beyond the single status
strip; authentication; deployment config; a generalized question/task
queue (explicitly deferred until a second question type exists); WebSockets.

## Git workflow

- Branch: `advisor/011-labeling-interface`; short lowercase imperative
  commits; do NOT push.

## Steps

### Step 1: server module

Create `app/labeling/server.py` with a FastAPI app factory:

```python
def create_app(db_path: str | Path) -> FastAPI: ...
```

Endpoints (all logic delegates to existing `app.x` functions):

- `GET /` — HTML page (a module-level template string). Shows: the oldest
  unreviewed post (handle, posted_at, full text, link to post_url), a
  count of remaining unreviewed posts, reads used/remaining this month,
  and the two actions.
- `GET /api/next` — JSON: next unreviewed post or `{"empty": true}` plus
  the counts (the page's JS calls this after every action so the flow
  never reloads).
- `POST /api/skip` — body `{"post_id": ...}` → `mark_reviewed(...,
  "skipped")`; returns the next-post payload.
- `POST /api/capture` — body: pydantic request model with post_id, claim,
  primary_theme_id, tickers (list), claim_type, stance, horizon,
  scrutiny_verdict, why_it_matters. Builds `CapturedSignal`
  (entry_id=`xs_<post_id>`, captured_at=now UTC, post fields copied from
  the stored post) and calls `save_signal`. Invalid enum values must
  return 422 (FastAPI does this via the model — use the real StrEnums in
  the request model). Returns the next-post payload.

Page behavior (vanilla JS in the template): `s` key or Skip button skips;
`c` opens the capture form; theme ids render as a button/radio grid;
claim_type/stance/horizon/verdict as radio groups; claim and
why_it_matters as text inputs; submit posts and advances. Keep the JS
dumb — no state beyond the current post.

The app must open its SQLite connection per request or with
`check_same_thread=False` handled deliberately — note which you chose and
why in one comment. (sqlite3 default connections are thread-bound;
uvicorn may serve from a worker thread.)

**Verify**: `python -c "from app.labeling.server import create_app; create_app(':memory:')"` → exit 0.

### Step 2: entrypoint

`python -m app.labeling.server --db data/boustrategy.db` runs
`uvicorn.run(app, host="127.0.0.1", port=8377)`. The host is a literal —
never a parameter.

**Verify**: start it against a temp db, `curl http://127.0.0.1:8377/`
returns HTML containing "no unreviewed posts" (or equivalent empty state),
then stop it. (Windows: use `Invoke-WebRequest` or httpx in a python -c if
curl is unavailable.)

### Step 3: dependency + tests

Add `fastapi>=0.111` and `uvicorn>=0.30` to `[project.dependencies]`;
`python -m pip install "fastapi>=0.111" "uvicorn>=0.30"`. Write tests per
the Test plan with `fastapi.testclient.TestClient` (uses the installed
httpx). Run all four gates.

## Test plan

`tests/labeling/test_server.py`, seeding posts via `insert_new_posts`
against `connect(":memory:")` — note: TestClient + in-memory SQLite means
the app factory must accept an existing connection OR a path; provide
`create_app` a seam for tests (e.g. accept `conn` for testing, path in
production — keep it explicit, not clever). Tests:

1. `test_next_returns_oldest_unreviewed` — two posts, `/api/next` returns
   the older one with remaining count 2.
2. `test_skip_marks_and_advances` — skip post A → A is `skipped` in the
   db, response contains post B.
3. `test_capture_saves_signal_and_marks_post` — capture with valid fields
   → signal row exists (entry_id `xs_<post_id>`), post `captured`,
   response advances.
4. `test_capture_rejects_unknown_enum_value` — stance="vibes" → HTTP 422,
   post still unreviewed.
5. `test_empty_queue_state` — no posts → `/api/next` returns
   `{"empty": true, ...}` and `GET /` renders the empty state.
6. `test_capture_is_idempotent` — capturing the same post twice with
   identical fields: second returns success without error (save_signal
   returns False path) and exactly one signal row exists.

Verification: `python -m pytest -q` → all pass (86 existing + 6 new = 92).

## Done criteria

- [ ] `python -m pytest -q` exits 0; 6 new tests under `tests/labeling/`
- [ ] All four plan-004 gates exit 0
- [ ] `grep -n '127.0.0.1' app/labeling/server.py` → present; `grep -n '0\.0\.0\.0' app/labeling/` → no matches
- [ ] `grep -rln "import fastapi\|from fastapi" app/` → only `app/labeling/server.py`
- [ ] No new functions added to `app/x/` (`git diff --stat` shows no app/x changes)
- [ ] The step-2 live check output is included in your report
- [ ] `git status --porcelain` clean after commit; only in-scope files changed
- [ ] `plans/README.md` status row updated (skip if reviewer-dispatched)

## STOP conditions

- The `app/x` function signatures don't match "Current state".
- You find yourself adding business logic (validation beyond the request
  model, new status values, new queries with judgment in them) — the thin-
  skin rule is the design; report instead.
- mypy strict cannot pass on the FastAPI code without more than narrow
  `ignore_missing_imports` overrides — report the specifics.

## Maintenance notes

- This page is the seed of the maintainer-judgment surface: eval grading
  and account-curation approvals attach here LATER as new pages/queues —
  and only then does a generalized question model earn its existence.
- When the relevance gate exists, its yes/no/maybe verdict belongs on this
  page as context next to each post (show the machine's opinion, capture
  the human's).
- The CLI `review` command remains as fallback; if the two drift, the UI
  is authoritative for daily use.
