# Plan 027: Newsletter ingestion v0 — drop folder, archive, annotation store

> Executor instructions: follow exactly; verify each step; STOP on
> mismatch. Branch `advisor/027-newsletter-drop-folder`, do NOT push,
> don't touch plans/README.md. Never reference any real database path
> in tests.

## Status

- Priority P3. Effort S-M. Depends on 006 (done); soft on 019 (amends
  WEEKLY.md if it exists). Independent of everything else — parallel
  runway. Planned at local main `088c69e`, 2026-07-18.

## Why this matters

Maintainer-approved 2026-07-15: curated newsletters (Citrini Research,
SemiAnalysis, …) via the maintainer's own subscriptions are the curated
corpus's second source class after X, weighed heavily narrative-wise
per the NOTES vision. The recorded open decision was per-source
delivery (email parsing vs manual drop). v0 sidesteps it: a manual drop
folder works for EVERY source today and loses nothing if email parsing
arrives later. Private-archive doctrine applies absolutely: internal
reference only, never republished, never surfaced on any public page.

## Current state (local main `088c69e`)

- `app/x/signals.py`: `CapturedSignal` field vocabulary (claim,
  claim_type, stance, horizon, scrutiny_verdict, why_it_matters) — the
  annotation model mirrors it.
- `app/schemas/decision_record.py`: `SourceType` includes
  INTERNAL_MEMO — the trust prior newsletters inherit.
- `data/` is gitignored except committed artifacts; verify `.gitignore`
  treatment of new paths and keep newsletter CONTENT out of git (the
  archive is content; the db rows are metadata).
- No `app/newsletters/`, no tables.

## Scope

IN: `app/storage/database.py` (two tables), `app/newsletters/` (create),
`data/newsletters/inbox/` + `archive/` (created at runtime, content
gitignored — add explicit `.gitignore` entries), WEEKLY.md one-step
amendment, tests.
OUT: email parsing (per-source maintainer decision, deferred as
recorded), PDF text extraction (v0 accepts .md/.txt only; PDFs are
archived but marked `unparsed` for manual conversion), any LLM calls,
any dashboard/public surface.

## Design

### Tables (append to `_SCHEMA`)

```sql
CREATE TABLE IF NOT EXISTS newsletter_docs (
    doc_id TEXT PRIMARY KEY,          -- sha256[:16] of file bytes
    source TEXT NOT NULL,             -- from filename prefix, see below
    title TEXT NOT NULL,
    received_at TEXT NOT NULL,
    archive_path TEXT NOT NULL,
    parse_status TEXT NOT NULL        -- parsed | unparsed
);
CREATE TABLE IF NOT EXISTS newsletter_claims (
    claim_id TEXT PRIMARY KEY,        -- 'nl_<doc_id>_<n>'
    doc_id TEXT NOT NULL,
    claim TEXT NOT NULL,
    claim_type TEXT NOT NULL,         -- fact | interpretation
    stance TEXT NOT NULL,             -- CapturedSignal Stance vocabulary
    horizon TEXT NOT NULL,
    tickers TEXT NOT NULL DEFAULT '[]',
    primary_theme_id TEXT NOT NULL DEFAULT '',
    why_it_matters TEXT NOT NULL DEFAULT '',
    annotated_by TEXT NOT NULL,       -- session name or 'maintainer'
    annotated_at TEXT NOT NULL
);
```

Both append-only. Claims reuse the `CapturedSignal` enums (import, do
not redefine); scrutiny_verdict deliberately absent — INTERNAL_MEMO
sources carry a standing trust prior instead of per-claim scrutiny;
revisit only if evals show the prior is wrong.

### Drop-folder convention

Maintainer drops files into `data/newsletters/inbox/` named
`<source>--<title>.<ext>` (e.g. `citrini--ai-power-buildout.md`).
Missing `--` separator → source `unknown` with a warning, never a
crash (a lazy filename must not block ingestion).

### CLI: `python -m app.newsletters.run <command> --db PATH`

- `ingest` — for each inbox file: hash → dedup (known doc_id: report,
  remove inbox copy, done); move to
  `archive/<source>/<doc_id>-<original-name>`; insert row
  (`parsed` for .md/.txt, `unparsed` otherwise). Idempotent: crash
  between move and insert must be recoverable by re-running (archive
  scan on startup reconciles files without rows).
- `annotate --doc DOC_ID --in FILE` — ingest claim-annotation JSONL
  (fields per table; validate enums; reject unknown doc_id). Written
  for a future annotation session or the maintainer by hand; nothing
  schedules it in v0.
- `list [--source X]` — docs with claim counts.

### WEEKLY.md amendment (only if plan 019 is merged)

Add one step: "Run `newsletters list` for docs ingested this week;
list new titles (title + source only, no content) in the weekly
synthesis under 'New internal reference'; flag `unparsed` docs to the
maintainer for conversion." Sessions do NOT annotate in v0.

## Steps

1. Tables + ingest with dedup/idempotency (tests: rerun after
   simulated crash between move and insert; duplicate drop; bad
   filename → unknown source; pdf → unparsed).
2. `annotate` validation matrix + `list`.
3. `.gitignore` entries + a test asserting archive content paths are
   ignored (`git check-ignore`).
4. WEEKLY.md step (or a noted skip if 019 unmerged).
5. Gates: pytest -q, ruff check, ruff format --check, mypy app tests →
   all exit 0; `git status --porcelain` clean after commit.

## STOP conditions

- You find yourself committing newsletter content to git, adding an
  email client/IMAP dependency, or writing PDF-parsing code.
- Any test needs the real database.
- Current-state signatures don't match local main `088c69e`.

## Maintenance notes

- Per-source email parsing remains the maintainer's recorded open
  decision; when made, the parser lands as a new inbox-feeder that
  reuses this ingest path unchanged.
- Annotation quality is a capability-handover problem — when the
  maintainer wants sessions annotating, run the plan 015 methodology
  (blind sample → judge → score) against maintainer-annotated docs
  first.
- The reasoning worker's intake (plan 025) can later include recent
  newsletter claims; deliberately not wired in v0 to keep both plans
  closed.
