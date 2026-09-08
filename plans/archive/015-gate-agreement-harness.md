# Plan 015: Gate-agreement experiment harness — export, ingest, score

> Executor instructions: follow exactly; verify each step; STOP on mismatch.
> Branch `advisor/015-gate-agreement-harness`, do NOT push, don't touch
> plans/README.md. Never reference any real database path in tests.

## Status

- Priority P1. Effort S-M. Depends on trial labels existing (they do:
  1,761 labeled posts on the live db). Planned at local main `f4dc9c9`,
  2026-07-15.

## Why this matters

The trial produced 1,761 human-labeled posts (63% positive). The next
component — relevance gate for the future scan tier, ranker/digest for the
core tier — must be built against measured model-vs-maintainer agreement,
not guesses. Maintainer decision (2026-07-15): no LLM API for this;
judging is done by subscription agent sessions (Codex/Claude goal mode,
e.g. gpt-5.6-luna/terra). So the harness is file-based: EXPORT unlabeled
batches to JSONL, an external agent judges them and writes prediction
files, INGEST loads them, SCORE measures agreement.

**Blind-labeling discipline (hard rule)**: export files must NOT contain
`review_status` or anything derived from it. The judging agent works only
from export files, never the database. Scoring joins predictions to human
labels only at score time.

## Current state (local main `f4dc9c9`)

- `app/storage/database.py`: `_SCHEMA` + `_ensure_columns` helper; tables
  incl. `x_posts` (post_id, handle, posted_at, text, url, fetched_at,
  review_status: unreviewed|captured|skipped|significant, conversation_id,
  reply_context, media_json).
- `app/x/posts.py`: `XPost`, `MediaItem`, `_media_from_row`.
- `app/labeling/server.py`: review UI (unrelated; do not modify).
- Conventions (`AGENTS.md`): crash early, plain functions, append-only,
  tests mirror app/. Gates: pytest, ruff check, ruff format --check, mypy
  strict.

## Scope

IN: `app/storage/database.py` (one new table), `app/labeling/experiment.py`
(create), `tests/labeling/test_experiment.py` (create).
OUT: everything else. No LLM calls anywhere. No changes to x_posts.

## Design

New table (append to `_SCHEMA`):

```sql
CREATE TABLE IF NOT EXISTS x_gate_predictions (
    post_id TEXT NOT NULL,
    predictor TEXT NOT NULL,
    prediction TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    predicted_at TEXT NOT NULL,
    PRIMARY KEY (post_id, predictor)
);
```

`prediction` values: `significant | skip`. `predictor` is a free string
naming the model/session (e.g. "gpt-5.6-luna"), so multiple predictors can
be compared.

CLI: `python -m app.labeling.experiment <command> --db <path>`:

- `export --out DIR [--batch-size 50]` — select ALL reviewed posts
  (review_status != 'unreviewed'), ordered by post_id (stable), and write
  `DIR/batch_001.jsonl`, `batch_002.jsonl`, ... Each line:
  `{"post_id", "handle", "posted_at", "text", "reply_context",
  "media": [{"url","media_type","alt_text"}], "url"}` — NO review_status,
  NO fields derived from labels. Also write `DIR/RUBRIC.md` (content
  below) so a judging session has the rubric alongside the data. Print
  batch and post counts.
- `ingest --predictor NAME --in FILE_OR_DIR` — read JSONL lines
  `{"post_id", "prediction", "reason"?}`; validate prediction value;
  INSERT OR REPLACE into x_gate_predictions with predicted_at=now UTC.
  Reject (raise) any post_id not present in x_posts. Print ingested count.
- `score --predictor NAME [--out FILE]` — join predictions to human
  labels (human positive = review_status IN ('significant','captured');
  human negative = 'skipped'). Report, printed and optionally written to
  `--out` as markdown: overall agreement %, confusion matrix
  (TP/FP/TN/FN with human as truth), precision/recall for positive class,
  per-handle agreement table, per-modality (has media vs text-only)
  agreement, and counts of predictions lacking a human label or vice
  versa. Also write the 50 most interesting disagreements (FP and FN,
  balanced) with post text snippets to the out file for maintainer review.

RUBRIC.md content (write verbatim into export dir; this is the judging
standard, distilled from docs/source_policy.md and the trial rules in
docs/x_manual/README.md):

```markdown
# Gate rubric v0 (from the maintainer's trial-week labeling bar)

Label each post `significant` or `skip`. Judge ONLY from the post content
provided (text, reply context, media). You may open media URLs to view
images. Never guess a label from the account name alone, though the
account's domain may inform how you read technical claims.

significant = the post contains a substantive claim that could, even two
steps removed, change how an AI/tech/markets theme is scored, seed or kill
an investment thesis, or shift a regime input. This includes model/
capability advancements, research results, supply-chain facts, capex and
demand signals, credible skepticism, and market-structure observations.
Tickers and direct financial content are NOT required.

skip = no articulable claim: vibes, hype without substance, pure jokes or
engagement bait, personal chatter, congratulation/reply noise, content
whose only substance sits behind an unfetched link you cannot evaluate.

When torn, skip. Output one JSON line per post:
{"post_id": "...", "prediction": "significant" | "skip", "reason": "<=15 words"}
```

## Steps

1. Table DDL + `export` with blind-export test coverage.
2. `ingest` with validation (bad prediction value raises; unknown post_id
   raises; re-ingest same predictor+post replaces).
3. `score` with a small synthetic fixture (seed posts + labels +
   predictions; assert the confusion matrix, precision/recall, and that
   per-handle rows appear).
4. Tests must include: export contains NO `review_status` key anywhere in
   any line (explicit assertion over raw file text: `"review_status" not
   in content`); export excludes unreviewed posts; batch splitting; the
   RUBRIC.md is written.
5. Gates: pytest -q (report count), ruff check, ruff format --check, mypy
   app tests → all exit 0; `git status --porcelain` clean after commit.

## STOP conditions

- Current-state signatures don't match local main `f4dc9c9`.
- You find yourself importing an LLM client or calling any network API —
  the harness is file-based by design.
- Any test needs the real database — synthetic only.

## Maintenance notes

- The RUBRIC.md doubles as the seed of the production gate prompt; expect
  the maintainer to iterate on it after seeing disagreement clusters.
- Multiple predictors are first-class: run Luna and Terra separately and
  `score` each; inter-model comparison can be eyeballed from the two
  reports (a `compare` command is deliberately deferred).
- The production gate, whenever it exists, re-runs this same harness with
  its real model as predictor — this file format is the eval contract.
