# Retired subsystems

Code removed from the tree but preserved in git. Each entry gives the
restore command; the tag `archive/2026-09-retirements` holds the final
state of every file listed here. To browse without restoring:
`git show archive/2026-09-retirements:<path>`.

## Labeling subsystem (retired 2026-09-08, plan 037)

- What: local review inbox (`python -m app.labeling.server`, port 8377), gate-agreement experiment harness (`app/labeling/experiment.py`), adjudication UI (`app/labeling/adjudication.py`), and their tests.
- Why: maintainer decision 2026-07-15 (`plans/archive/README.md`, “No ongoing manual labeling”); the gate experiment completed with Luna at 72.5% raw agreement over 1,761 posts (`docs/research/gate_experiment_findings.md`).
- Data kept: source-database tables `x_posts`, `x_signals`, `x_gate_predictions`, `x_adjudications`, and `x_score_snapshots` are untouched. The X pipeline still uses `x_posts` and `x_signals`.
- History: `DEVELOPMENT.md`, “Learning what a useful X feed looks like,” and plans 011, 015, and 016 under `plans/archive/`.
- Restore: `git checkout archive/2026-09-retirements -- app/labeling tests/labeling` (no additional dependencies need to be installed).

## X replay study tool (retired 2026-09-08, plan 037)

- What: the lookahead-aware research replay CLI in `app/x/replay.py` and its tests.
- Why: the study is complete, its findings are recorded, and no production code called the tool.
- History: `DEVELOPMENT.md`, “Replaying the old data without pretending it knew the future.”
- Restore: `git checkout archive/2026-09-retirements -- app/x/replay.py tests/x/test_replay.py`.

## Public API v1 and source projector (retired 2026-09-08, plan 037)

- What: `/api/public/v1/dashboard`, `/api/public/v1/decisions/{ticker}/{created_at}`, `app/public/projection.py`, the `legacy_dashboard` and `legacy_decision` adapters, `app/public/models.py`, and their v1-only tests.
- Why: v1 was never published and was superseded by v2 over the published store. Old links resolve through `/api/public/v2/legacy-decisions/{ticker}/{created_at}`.
- Restore: `git checkout archive/2026-09-retirements -- app/public/projection.py tests/public/test_public_dashboard.py`. To inspect the routes and adapters before restoring them, run `git show 579a724:app/public/server.py` and `git show 579a724:app/public/queries.py`.
