# Plan 016: Adjudication UI — resolve human-vs-model disagreements, correct labels, re-score, compare rounds

> Executor instructions: follow exactly; verify each step; STOP on mismatch.
> Branch `advisor/016-adjudication-ui`, do NOT push, don't touch
> plans/README.md. Tests synthetic only — never any real database path.

## Status

- Priority P1. Effort M. Depends on 011 (labeling server), 015 (harness +
  ingested predictions). Planned at local main `829507b`, 2026-07-15.

## Why this matters

The gate experiment scored gpt-5.6-luna at 72.5% agreement over 1,761
posts (485 disagreements: 232 FP, 253 FN). Review showed disagreements
split three ways: model errors, HUMAN label errors (e.g. non-English
posts the maintainer skipped at the language barrier but the model read
natively), and genuine borderline cases. Maintainer decisions
(2026-07-15): no ongoing manual labeling; instead, one adjudication
surface where each disagreement is reviewed once — uphold my label /
model was right / borderline — with overturns correcting the stored
label (auditably), live re-scoring, and a before/after comparison so
rounds converge "until we come to a point."

## Design decisions (made; do not revisit)

- Lives in the EXISTING labeling server (`app/labeling/server.py`) as a
  second page at `/adjudicate` — same localhost-only binding, same
  per-request connections, same self-contained template pattern (no
  external resources).
- **Label corrections are real but audited**: an "overturned" verdict
  flips `x_posts.review_status` between `significant` and `skipped`
  ONLY. Posts with status `captured` are never auto-flipped (they carry
  rich signals); their verdicts are recorded with a `needs_manual_review`
  note instead. Every adjudication is an append-only row — the original
  label is preserved in the adjudication record.
- **Borderline** records the verdict, flips nothing, and scoring reports
  agreement both including and excluding borderline-adjudicated posts.
- One adjudication per (post_id, predictor): re-adjudicating replaces the
  verdict (INSERT OR REPLACE) and re-applies/reverts the flip
  consistently (verdict change from overturned→upheld must restore the
  original label; store `label_before` in the row to make this exact).
- Round comparison: a snapshot row is written automatically at the START
  of an adjudication session's first verdict (if none exists yet for the
  predictor) capturing the original metrics; the UI header always shows
  original snapshot vs live-recomputed metrics + adjudication progress.

## Current state (local main `829507b`)

- `app/labeling/server.py`: FastAPI `create_app(db_path_or_conn)`;
  routes `/`, `/api/next`, `/api/skip`, `/api/flag`, `/api/capture`;
  module-level HTML template string with vanilla JS; `_render_media`;
  error-banner + `handleResponse` pattern; per-request `get_conn()`.
- `app/labeling/experiment.py`: `score_predictor(conn, predictor) ->
  dict` (structured metrics: agreement, precision, recall, confusion,
  per-handle, per-modality, disagreements list with post_id/handle/text/
  human/prediction/reason), `render_report`, CLI export/ingest/score.
- `app/storage/database.py`: `_SCHEMA` + `_ensure_columns`;
  `x_gate_predictions` (post_id, predictor, prediction, reason,
  predicted_at; PK (post_id, predictor)).
- `app/x/posts.py`: XPost, `_media_from_row`; `mark_reviewed` only
  transitions FROM 'unreviewed' — adjudication flips must NOT use it
  (write a dedicated function; see steps).
- Live data context (do not touch in tests): 1,761 reviewed posts, 485
  disagreements for predictor `gpt-5.6-luna`.
- Gates: pytest (140), ruff check, ruff format --check, mypy strict.
- Known bug to fix in passing: the experiment CLI crashes printing
  non-cp1252 text on Windows consoles — reconfigure stdout to UTF-8 in
  `experiment.py` main().

## Scope

IN: `app/storage/database.py` (two tables), `app/labeling/adjudication.py`
(new: logic), `app/labeling/server.py` (routes + template additions),
`app/labeling/experiment.py` (stdout utf-8 fix + expose a
`score_predictor` variant that can exclude borderline post_ids if not
trivially composable), `tests/labeling/test_adjudication.py` (new).
OUT: everything else; no changes to x_posts columns, signals, x/ modules.

## Tables (append to _SCHEMA)

```sql
CREATE TABLE IF NOT EXISTS x_adjudications (
    post_id TEXT NOT NULL,
    predictor TEXT NOT NULL,
    verdict TEXT NOT NULL,
    label_before TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    adjudicated_at TEXT NOT NULL,
    PRIMARY KEY (post_id, predictor)
);
CREATE TABLE IF NOT EXISTS x_score_snapshots (
    predictor TEXT NOT NULL,
    label TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (predictor, label)
);
```

`verdict` values: `upheld | overturned | borderline`.

## Logic (`app/labeling/adjudication.py`)

- `pending_disagreements(conn, predictor) -> list[dict]` — disagreements
  (prediction vs human label mismatch) with NO adjudication row yet,
  ordered FN-first (human positive, model skip) then FP, oldest posted_at
  first within each; each dict carries the full post payload (text,
  reply_context, media, handle, posted_at, url), the human label, the
  model prediction + reason, and a `captured` flag.
- `adjudicate(conn, predictor, post_id, verdict, note="") -> dict` —
  validates verdict; snapshots original metrics on first-ever
  adjudication for this predictor (label='original', INSERT only if
  absent); records the row with label_before = current review_status;
  applies the flip rule (overturned + significant↔skipped only; captured
  → record verdict, never flip; note auto-appended 'needs_manual_review'
  for captured); re-adjudication restores label_before first, then
  applies the new verdict's effect. Returns the next pending payload +
  live metrics (same shape as the UI needs).
- `adjudication_progress(conn, predictor) -> dict` — total
  disagreements, adjudicated count, verdict breakdown, original-snapshot
  metrics, live metrics (score_predictor now), and live metrics excluding
  borderline-adjudicated posts.

## Routes + page

- `GET /adjudicate?predictor=NAME` — page: header comparison strip
  (original vs live agreement/precision/recall, progress N/485), then
  the current disagreement: full post block (reuse media/context
  rendering), YOUR LABEL vs MODEL (with its reason) side by side, three
  buttons + keys: **1** uphold mine / **2** model was right / **3**
  borderline, optional note field, error banner. Advances on verdict via
  `POST /api/adjudicate` (same handleResponse pattern).
- `GET /api/adjudicate/next?predictor=` and `POST /api/adjudicate`
  (body: predictor, post_id, verdict, note) — thin skins over the logic
  module.
- Empty state: "all disagreements adjudicated" + final comparison.

## Tests (tests/labeling/test_adjudication.py, synthetic)

1. pending_disagreements returns only mismatches without adjudications,
   FN before FP.
2. overturned FP flips skipped→significant; overturned FN flips
   significant→skipped; label_before stored.
3. upheld and borderline flip nothing.
4. captured post: verdict recorded, status unchanged, note flags manual
   review.
5. re-adjudication: overturned→upheld restores the original label.
6. first adjudication writes the 'original' snapshot exactly once.
7. progress reports live metrics differing from snapshot after an
   overturn (agreement improves when a human error is corrected).
8. UI: GET /adjudicate renders comparison strip; POST advances and
   returns next + metrics; invalid verdict → 422 and nothing changes.
9. stdout utf-8: experiment CLI main reconfigures stdout (unit-test the
   helper or verify no crash printing a non-cp1252 string with the
   reconfigure applied — keep it simple and honest).

## Gates

`python -m pytest -q` (report count), ruff check, ruff format --check,
mypy app tests — all exit 0; `git status --porcelain` clean after commit.

## STOP conditions

- Current-state signatures don't match `829507b`.
- You find yourself using `mark_reviewed` for flips (it only allows
  transitions from 'unreviewed' — the dedicated path exists for a reason).
- Anything requires touching real data or non-in-scope files.

## Maintenance notes

- Adjudicated labels change the answer key: any earlier report file is
  stale after a session; re-run score for current truth (the UI shows
  live numbers precisely so stale files don't mislead).
- If a second predictor (Terra) is ever run, adjudications are
  per-predictor by design, but label flips are global — adjudicating
  predictor A can change predictor B's score. That's correct (labels are
  the shared truth) but worth remembering when comparing.
- The maintainer decided against ongoing labeling: this UI is the
  closing loop for the current dataset, not a recurring duty.
