# Plan 018: X pipeline backbone — run ledger, routing store, article queue, digest renderer, market calendar

> Executor instructions: follow exactly; verify each step; STOP on mismatch.
> Branch `advisor/018-x-pipeline-backbone`, do NOT push, don't touch
> plans/README.md. Never reference any real database path in tests.

## Status

- Priority P1. Effort M. Depends on plans 010-014 (all DONE on main).
  Planned at local main `a97a85f`, 2026-07-18.

## Why this matters

The trial and gate experiment are complete (85.2% corrected agreement;
`docs/research/gate_experiment_findings.md`) and the maintainer approved
handing the daily judging loop to a subscription agent session. This plan
builds the deterministic half of that loop: the run ledger, the routing
store, the article queue, the digest renderer, and the market calendar.
The LLM half (rubric v2, session runbooks) is plan 019.

Maintainer decisions from the 2026-07-18 planning session that this plan
implements structurally:

- **Three weekday slots + Sunday weekly**: 08:45, 12:30, and 17:45 ET
  (post-close — captures after-hours earnings same day; on half-days the
  close slot shifts to 14:45), plus Sunday 18:00 ET. The daily digest
  closes after the close run; later developments flow into the next
  morning's run.
- **The digest is the seam**: ingestion runs NEVER launch reasoning or
  thesis-chain sessions. Actionable items get flagged in the digest;
  the (future, checkpoint-5-gated) reasoning worker consumes them as its
  own session. Nothing in this plan calls an LLM.
- **Always-flag rule enforced in code, not prompt**: link-only posts from
  roster accounts route to the article queue mechanically, before any
  model judgment (finding 2: 76%-positive class, invisible to the API).
- **Ground truth stays frozen**: the trial labels in
  `x_posts.review_status` are the eval ground truth. Production routing
  NEVER writes `review_status`; it lives in a new table.

## Current state (local main `a97a85f`)

- `app/storage/database.py`: `_SCHEMA` executescript + `_ensure_columns`;
  tables incl. `x_accounts` (handle, user_id, categories, tier, status),
  `x_posts` (review_status: unreviewed|captured|skipped|significant,
  reply_context, media_json), `x_post_reads` (month, post_reads).
- `app/x/run.py`: commands seed|fetch|review|status|rehydrate;
  `_cmd_fetch` reads `list_active_accounts(conn, tier="core")`, resolves
  missing user_ids, computes since_id via `MAX(CAST(post_id AS INTEGER))`
  per handle, honors `_BUDGET_FLOOR = 100`.
- `app/x/posts.py`: `MAX_MONTHLY_POST_READS = 5900` (trial top-up; the
  maintainer recalibrates this constant separately — do not change it),
  `record_post_reads`, `reads_remaining`, `insert_new_posts`.
- `app/labeling/experiment.py`: `export_batches` writes blind JSONL
  batches (`post_id, handle, posted_at, text, reply_context, media, url`)
  — reuse this line shape for run exports.
- Conventions (`AGENTS.md`): crash early, plain functions, append-only,
  tests mirror app/. Gates: pytest, ruff check, ruff format --check,
  mypy strict.

## Scope

IN: `app/storage/database.py` (three new tables), `app/x/calendar.py`
(create), `app/x/pipeline.py` (create), `app/x/run.py` (new subcommands;
one-line fetch change), tests mirroring each.
OUT: everything else. No LLM calls. No scheduler installation (ops, plan
019). No rubric content (plan 019). No labeling-server changes. No
changes to `review_status` values or semantics anywhere.

## Design

### New tables (append to `_SCHEMA`)

```sql
CREATE TABLE IF NOT EXISTS x_runs (
    run_id TEXT PRIMARY KEY,          -- '<YYYY-MM-DD>-<slot>'
    slot TEXT NOT NULL,               -- morning | midday | close | weekly
    started_at TEXT NOT NULL,
    finished_at TEXT,
    posts_fetched INTEGER NOT NULL DEFAULT 0,
    posts_exported INTEGER NOT NULL DEFAULT 0,
    reads_used INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'started'
    -- started | exported | routed | digested | failed
);
CREATE TABLE IF NOT EXISTS x_route_decisions (
    post_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    route TEXT NOT NULL,              -- digest | article_queue | skip
    rank TEXT NOT NULL DEFAULT '',    -- headline | notable | context | ''
    reason TEXT NOT NULL DEFAULT '',
    predictor TEXT NOT NULL,          -- session name, or 'code:link_only'
    decided_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS x_article_queue (
    post_id TEXT PRIMARY KEY,
    queued_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | summarized | dismissed
    resolution TEXT NOT NULL DEFAULT ''
);
```

### `app/x/calendar.py`

No new dependency. A static NYSE table with an explicit coverage window;
beyond coverage the module raises `CalendarCoverageError` (staleness must
fail loud, never silently skip runs). Times via
`zoneinfo.ZoneInfo("America/New_York")`.

- `COVERAGE_END = date(2026, 12, 31)`.
- Full-close holidays remaining in coverage: 2026-09-07 (Labor Day),
  2026-11-26 (Thanksgiving), 2026-12-25 (Christmas).
- Half-days (13:00 close): 2026-11-27, 2026-12-24.
- `run_slots(d: date) -> list[tuple[str, time]]`:
  - raises `CalendarCoverageError` if `d > COVERAGE_END`;
  - Sunday → `[("weekly", 18:00)]` (runs even when Monday is a holiday);
  - Saturday or full-close holiday → `[]`;
  - trading weekday → morning 08:45, midday 12:30, close 17:45;
  - half-day → morning 08:45, close 14:45 (no midday; the session is
    three hours shorter and the midday slot would land near the close).
- `slot_should_run(d, slot) -> time | None` convenience wrapper.

This makes a dumb "fire every day at each slot time" scheduler safe: the
`cycle` command itself checks the calendar and exits 0 as a no-op on
non-trading days/slots.

### `app/x/pipeline.py` + new `app/x/run.py` subcommands

`cycle --slot SLOT [--date YYYY-MM-DD] [--out DIR]` (default out
`data/x_runs/<run_id>/`):

1. Calendar check via `slot_should_run`; if the slot doesn't run today,
   print and exit 0 (no run row). `weekly` slot: steps 2-5 are skipped
   except the run row — the weekly run fetches nothing itself (Sunday
   posts are caught by Monday morning); it exists so `weekly-render` has
   a ledger anchor.
2. Insert `x_runs` row (status `started`). Duplicate run_id → crash
   early (re-running a completed slot is a maintainer decision, not an
   auto-overwrite).
3. Fetch: existing `_cmd_fetch` logic but over ALL active accounts
   (`list_active_accounts(conn)` — drop `tier="core"`; the 2026-07-15
   decision is a single full-fetch tier). Record `posts_fetched` and
   `reads_used` (diff `reads_remaining` before/after) on the run row.
   Budget guard behavior unchanged.
4. Auto-route link-only posts: for each newly-fetched post with
   `review_status = 'unreviewed'`, no `x_route_decisions` row, at least
   one URL in text, empty media, and ≤ 40 chars of text after stripping
   URLs and whitespace → insert route `article_queue`
   (predictor `code:link_only`) + `x_article_queue` row. Constant
   `LINK_ONLY_MAX_CHARS = 40`.
5. Export for judging: posts with `review_status = 'unreviewed'`, no
   `x_route_decisions` row, and `fetched_at >=` the previous finished
   run's `started_at` (first run ever: last 24h — this cutoff also keeps
   any stray unreviewed trial-era posts out of production digests).
   Reuse the `export_batches` line shape into `DIR/batch_*.jsonl` and
   copy `docs/x_pipeline/RUBRIC.md` into DIR if it exists (it arrives
   with plan 019; absence is not an error, print a notice). Set status
   `exported`, print counts + budget headroom.

`route --run RUN_ID --predictor NAME --in FILE_OR_DIR`:

- Read prediction JSONL lines
  `{"post_id", "prediction": "significant"|"skip", "rank"?, "reason"?}`.
- Validate: prediction value; `rank` required and one of
  headline|notable|context when significant, must be absent/empty when
  skip; post_id must exist in x_posts; reject post_ids already routed by
  a DIFFERENT run (same-run re-ingest replaces, mirroring plan 015).
- significant → route `digest` with rank; skip → route `skip`.
- Never touches `review_status`. Set run status `routed`, print counts.

`digest-render --date YYYY-MM-DD [--out FILE]` (default
`data/digests/<date>.md`), deterministic renderer over that date's runs:

- Header: date, runs completed, roster size.
- `## Actionable` — headline-ranked items: handle, posted_at, text
  snippet (first 280 chars), reason, url. If any exist, the header line
  gets a literal `ACTIONABLE` marker (the future reasoning worker's
  pickup signal — nothing in this plan acts on it).
- `## Notable` and `## Context` — same shape, tighter snippets.
- `## Article queue` — ALL `pending` x_article_queue items (not just
  today's), oldest first, with url and queued_at.
- `## Synthesis` — the literal placeholder text
  `_(session-authored; see docs/x_pipeline/DIGESTER.md)_` between
  `<!-- synthesis:start -->` / `<!-- synthesis:end -->` markers. The
  renderer must preserve existing content between the markers on
  re-render (runs re-render the same file three times a day).
- `## Ops` — per-run rows (slot, fetched, exported, routed, reads_used),
  monthly reads used/remaining, any run with status `failed`/stuck.
- Marks the day's runs `digested`.

`weekly-render --date YYYY-MM-DD [--out FILE]` (default
`data/digests/weekly-<date>.md`): aggregates the prior 7 days —
headline items list, per-account counts (fetched vs digest-rank
distribution; feeds roster audition decisions), pending + resolved
article-queue items, ops totals. Same preserved synthesis block. The
narrative (thesis review, watchlist, open questions) is session-authored
per plan 019's WEEKLY runbook, not rendered here.

## Steps

1. Tables DDL + calendar module with tests (holiday, half-day shift,
   Sunday weekly, Saturday empty, coverage error past 2026-12-31).
2. `cycle`: no-op path, run-row lifecycle, fetch-all-active change,
   link-only auto-route (tests: link-only detected; text+media post NOT
   detected; text-with-link-and-substance NOT detected), export cutoff
   (test: pre-cutoff unreviewed post excluded).
3. `route`: validation matrix tests (bad rank combos, unknown post_id,
   cross-run reject, same-run replace, review_status untouched —
   explicit assertion).
4. `digest-render` + `weekly-render`: synthetic fixture; assert section
   presence, ACTIONABLE marker only when headline items exist, synthesis
   block preserved across re-render, pending articles carry over.
5. Gates: pytest -q, ruff check, ruff format --check, mypy app tests →
   all exit 0; `git status --porcelain` clean after commit.

## STOP conditions

- Current-state signatures don't match local main `a97a85f`.
- You find yourself importing an LLM client or calling any network API
  other than the existing `app/x/client.py` fetch path.
- Any code path writes `x_posts.review_status` — production routing must
  not touch it.
- Any test needs the real database — synthetic only.
- You are tempted to change `MAX_MONTHLY_POST_READS` — that constant is
  the maintainer's budget dial.

## Maintenance notes

- **Before first production cycle** (maintainer, human checkpoint 2):
  trim the roster toward the ~20-account target (set `status` on
  `x_accounts` / re-seed) and recalibrate `MAX_MONTHLY_POST_READS`
  against the trial-measured volumes.
- The calendar table must be extended before 2027 trading begins;
  `CalendarCoverageError` is the deliberate tripwire.
- `x_article_queue.status` transitions (`summarized`/`dismissed`) are
  written by the article-reading flow (Grok pilot or human) — out of
  scope here; the queue is deliberately write-once/update-status.
- The digest close is convention, not lock: the close run's
  `digest-render` is simply the last one of the day.
