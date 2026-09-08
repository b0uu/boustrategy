# Plan 037: Retire the labeling subsystem, the replay tool and the public v1 path behind a recoverable archive, and move completed plans out of the live index

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 40b317b..HEAD -- app/labeling tests/labeling app/x/replay.py tests/x/test_replay.py app/dashboard/server.py app/regime/run.py`
> plus manual comparison for the UNTRACKED files `app/public/server.py`,
> `app/public/projection.py`, `app/public/publication.py`,
> `app/public/queries.py` (compare the excerpts below with
> `sed -n '<start>,<end>p' <file>`). On a mismatch, treat it as a STOP condition.
>
> **Ordering**: run this plan BEFORE plan 032. It deletes the public v1
> routes that 032's Steps 1, 2 and 4 would otherwise modify; after 037 lands,
> 032 shrinks to its Steps 3, 5 and 6 (checkpoint identity digest, X-excerpt
> rule) — 032 says so in its header.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED (large deletions; every deletion is recoverable from the archive tag)
- **Depends on**: none. Plans 035 and 036 are unaffected. Plan 032 is partly superseded (see Ordering).
- **Category**: tech-debt
- **Planned at**: commit `40b317b` (branch `advisor/030-private-dual-agent-dashboard`, working tree uncommitted), 2026-09-08

## Why this matters

The maintainer asked whether the codebase is bloated and, if so, to trim it.
The measured answer: not generically. App code is about 17,500 lines across
18 small packages, tests are about 11,800 lines, there are no tracked build
artifacts except a stray `skills-lock.json`, and only two symbols are dead.
The real weight is three whole subsystems whose purpose has ended, and a
plan/document history that has grown to about 9,500 lines beside the live
index:

| What | Size | Why it is finished |
|---|---|---|
| `app/labeling/` + `tests/labeling/` (review inbox, gate-agreement experiment, adjudication UI on port 8377) | 1,514 + 1,181 lines | Maintainer decision 2026-07-15: "no ongoing manual labeling"; the gate experiment is complete and written up in `docs/research/gate_experiment_findings.md` and `DEVELOPMENT.md`. Nothing in `app/` imports it. |
| `app/x/replay.py` + `tests/x/test_replay.py` (research replay CLI) | 401 + 120 lines | Research aid; no caller other than its own tests and its own `main()`. Findings are recorded in `DEVELOPMENT.md` ("Replaying the old data…"). |
| Public v1 API: two routes in `app/public/server.py`, all of `app/public/projection.py`, `legacy_dashboard`/`legacy_decision` in `app/public/queries.py`, and most of `app/public/models.py` | ~330 + ~95 + ~120 lines, plus ~10 v1-only tests | Three coexisting public read implementations; the React UI uses only v2; v1 has never been published anywhere; its source-database fallback is also a security fail-open (plan 032). |
| `render_x_snippet` (`app/dashboard/server.py:38-40`), `latest_published_regime` (`app/regime/run.py:25-33`) | trivial | No production callers. |
| Completed plans 001-031 and `plans/HUMAN_GUIDE.md` | ~9,500 lines | Executed history; the live index should show only what is still runnable. |

The maintainer's constraint on removal: **do not lose the labeling work, and
leave a trace so a future agent can answer questions about it.** Deleting
files is fully recoverable from git, but only if someone knows what to look
for. So this plan makes the trace explicit: a git tag on a snapshot commit
that contains every retired file in its final state, and a retirement ledger
at `docs/archive/README.md` that says what each subsystem was, why it was
retired, what data it left behind, where its findings live, and the exact
command to restore it. Agents reading the repo find the ledger by name; the
tag guarantees the restore command always works.

After this plan: about 4,500 lines of app and test code are gone from the
tree, the public API has one read path (v2 over the published store), the
private dashboard never touches the labeling or public code, the live plan
index is short, and everything removed is one documented command away.

## Current state

### Retired subsystems and their edges

- `app/labeling/server.py:20-32` imports `app.labeling.adjudication`, `app.storage.database.connect`, `app.storage.runtime.immediate`, `app.x.posts` (several names incl. `_media_from_row`), `app.x.signals` (several names). No module under `app/` imports `app.labeling`. Under `tests/`, only `tests/labeling/*` and two end-to-end tests in `tests/x/test_posts.py` (~lines 322-425) do; Step 2.3 migrates those two. `app/x/signals.py` and `app/x/posts.py` stay: they are used by `app/x/run.py` and `app/newsletters/store.py`.
- Labeling data lives in the source database tables `x_posts` (3,424 rows on the real db), `x_signals` (13), `x_gate_predictions`, `x_adjudications`, `x_score_snapshots` (schema in `app/storage/database.py:191-237`). These tables are ALSO used by the X pipeline (`app/x/*`) and must stay.
- `app/x/replay.py` has its own `main()` (line 369) and is not imported by `app/x/run.py` or anything else (`grep -rn "replay" app/x/run.py app/x/pipeline.py` → nothing).
- Docs that mention these: `README.md:29` ("labeling work" — a narrative sentence, keep), `DEVELOPMENT.md:36-60,82-99` (history, keep), `docs/x_manual/README.md:130` (labeling tiers, keep), `docs/research/gate_experiment_findings.md` (keep). `docs/plan-031-audit.md` rows for "Labeling" and replay studies are historical audit records; keep.

### Excerpt A — `app/public/server.py:15-19` (imports) and `:51-90` (v1 routes)

```python
from app.dashboard.queries import table_exists
from app.public import activity, projection, queries
from app.public.database import open_readonly
from app.public.exports import decision_csv
from app.public.models import PublicDashboard, PublicDecision
```

```python
    @app.api_route(
        "/api/public/v1/dashboard", methods=["GET", "HEAD"], response_model=PublicDashboard
    )
    def public_dashboard() -> PublicDashboard:
        if not published.exists():
            with open_readonly(path) as conn:
                return projection.dashboard(conn, include_history=False)
        with open_readonly(published) as conn:
            return queries.legacy_dashboard(conn)

    @app.api_route(
        "/api/public/v1/decisions/{ticker}/{created_at}",
        methods=["GET", "HEAD"],
        response_model=PublicDecision,
    )
    def public_decision(ticker: str, created_at: str) -> PublicDecision:
        ...
```

The v2 route `/api/public/v2/legacy-decisions/{ticker}/{created_at}` at
`server.py:295-310` resolves a ticker+timestamp to a public id and delegates
to the v2 detail handler. It is the supported replacement for old links and
MUST stay.

`create_public_app(db_path, frontend_dir, *, public_db_path)` at
`server.py:22-33` keeps the private source path as `path`; after v1 is gone
nothing reads it. `main()` at `:351-359` has `--db` and `--public-db`.

### Excerpt B — `app/public/projection.py` names used elsewhere

```
app/public/publication.py:459   if status in projection._PUBLIC_LIFECYCLE or status in {
app/public/publication.py:606   if status in projection._PUBLIC_LIFECYCLE
app/public/publication.py:657   and c.get("source_type") in projection._PUBLIC_SOURCE_TYPES
app/public/publication.py:900   paper = projection.dashboard(source, include_decisions=False, include_history=False).model_dump()
```

`projection.py:24-33` defines:

```python
_PUBLIC_LIFECYCLE = { ... }   # a set of lifecycle status strings (read the literal)
_PUBLIC_SOURCE_TYPES = {"SEC", "COMPANY_IR", "NEWS", "X", "PRICE_DATA", "MACRO", "ETF_ISSUER"}
```

### Excerpt C — `app/public/publication.py:899-916` (the only remaining projector use)

```python
            # The legacy paper adapter runs only at publication, not on v2 GET.
            paper = projection.dashboard(
                source, include_decisions=False, include_history=False
            ).model_dump()
            paper_view: dict[str, Any] = {
                "portfolio_id": "paper",
                "name": "BouStrategy paper",
                "mode": "paper",
                "is_default": False,
                "status": paper["performance"]["status"],
                "reason": None,
                "data_as_of": None,
                **paper["performance"],
                "positions": paper["positions"],
                "cash": None,
                "capabilities": {"returns": False, "cash": False, "quantities": True},
            }
            paper_view["return_percent"] = None
            paper_view["history"] = []
```

With `include_decisions=False, include_history=False`, `projection.dashboard`
contributes exactly: `performance = {"status", "equity", "return_percent", "history": []}`
and `positions = [PublicPosition(...)]` computed by `projection.py:121-186`:

- `has_paper_data` = any row in `paper_positions` or `paper_fills`, AND no contaminated fill (a `paper_fills` row whose `order_intents` row is missing or not `PAPER`).
- For each `paper_positions` row (`ticker, shares, avg_cost, primary_theme_id` ordered by ticker): latest `daily_prices.close` for the ticker (or `None`).
- `equity = cash_balance(conn) + Σ shares*price` only if every position has a price, else `None`. `cash_balance` is `app.paper.broker.cash_balance`; `STARTING_CASH` is `app.paper.broker.STARTING_CASH`.
- Each position dict: `ticker, shares, average_cost, latest_price, market_value (shares*price or None), weight (value/equity or None), unrealized_return_percent ((price/avg_cost - 1)*100 or None), theme (str or None), latest_public_summary (None here)`.
- `performance.status = "available" if equity is not None else "unavailable"`; `return_percent = (equity/STARTING_CASH - 1)*100 or None` — immediately overwritten to `None` by the caller.

### Excerpt D — `app/public/queries.py:13-24` (imports) and `:258-352`

```python
from app.dashboard.queries import table_exists
from app.public.models import (
    PublicDashboard, PublicDecision, PublicDecisionListItem, PublicOutcome,
    PublicPerformance, PublicPolicySummary, PublicPosition, PublicRegime, PublicXUsage,
)
```

These model names are used ONLY inside `legacy_dashboard` (258-303) and
`legacy_decision` (305-350). `app/public/exports.py` imports no models.
`app/public/models.py` (all 14 classes) will therefore have no importer after
this plan except `projection.py`, which is deleted.

### Excerpt E — tests that exercise v1

- `tests/public/test_public_dashboard.py` — entirely v1 (both tests + `_client`). Its second test, `test_public_projection_filters_sources_ids_and_live_details` (lines 31-130), carries the valuable assertion list of PRIVATE_* strings that must never appear in a public response. That assertion set must be PORTED to v2 before the file is deleted (Step 6).
- `tests/public/test_public_v2.py` lines 43, 123, 134, 364, 413, 430-434, 450-455, 461-466, 492, 533-536 — v1 calls inside otherwise-v2 tests; `test_published_legacy_detail_uses_publication_snapshot` (~446) and `test_legacy_feeds_are_bounded_with_independent_history_counts` (~458) are v1-only.
- `tests/public/test_release.py:42-43` — includes the two v1 paths in a route list.
- `tests/public/test_explanations.py:109,398` — two v1 calls.
- `public-ui/fixtures/generate.py` imports `create_public_app` and `publish` but does not call v1 routes (verify with `grep -n "v1" public-ui/fixtures/generate.py`).

### Excerpt F — dead symbols

```python
# app/dashboard/server.py:38-40
def render_x_snippet(text: str, public: bool = False) -> str:
    """Single future public-mode seam: public surfaces must use claim summaries."""
    return "[private snippet hidden]" if public else text[:280]
```

Only reference: `tests/dashboard/test_dashboard.py:10,199-203`
(`test_x_snippet_public_switch_is_single_seam`).

```python
# app/regime/run.py:25-33
def latest_published_regime(conn: sqlite3.Connection, on_date: date) -> RegimeState | None:
```

No references anywhere (`grep -rn latest_published_regime app tests` → only the definition).

### Excerpt G — plans index today

`plans/README.md` is 583 lines: header + maintainer notes (1-28), the
001-030 status table (29-74), human checkpoints (75-104), dependency notes
(105-130), **maintainer decisions (131-370, institutional memory — keep)**,
direction items (371-434), rejections (435-448), not-audited (449-454), the
plan 031 section (455-487), and the 2026-09-08 audit section (488-583) that
contains the live table for 032-036. `plans/HUMAN_GUIDE.md` (274 lines)
describes plans 001-004 and is referenced only from `plans/README.md:9-11`.
Plans 001-031 are all DONE.

### Repo conventions that apply

- AGENTS.md: no premature abstraction; explicit inline code; crash early; tests mirror `app/`.
- Commit style from `git log`: `fix:`, `feat:`, `docs:`, `chore:` prefixes.
- The tree has a large uncommitted delta that is NOT yours (plan 031's work). Stage only the paths this plan names, with explicit `git add`/`git rm` paths; never `git add -A` or `git add .`.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Full tests | `python -m pytest -q` | all pass |
| Lint | `python -m ruff check .` | `All checks passed!` |
| Format | `python -m ruff format --check .` | `N files already formatted` |
| Types | `python -m mypy app tests` | `Success: no issues found` |
| Frontend | `npm --prefix public-ui run test` | 26 pass |
| Fixture parity | `python public-ui/fixtures/generate.py` then `git diff --stat public-ui/fixtures/public-v2.json` | no diff (the generator must still produce identical fixtures) — if the script needs arguments, read its `main` first |
| Dead-reference sweep | `grep -rn "app.labeling\|app.x.replay\|projection\.\|legacy_dashboard\|legacy_decision\|render_x_snippet\|latest_published_regime\|/api/public/v1" app tests public-ui/src public-ui/fixtures docs ops README.md DEVELOPMENT.md --include=* \| grep -v __pycache__ \| grep -v "docs/archive/"` | only historical mentions in `DEVELOPMENT.md`, `docs/plan-031-audit.md`, `docs/research/`, `plans/archive/` |

## Scope

**In scope**:
- Delete: `app/labeling/` (all), `tests/labeling/` (all), `app/x/replay.py`, `tests/x/test_replay.py`, `app/public/projection.py`, `tests/public/test_public_dashboard.py`, `plans/HUMAN_GUIDE.md` (moved, not deleted).
- Edit: `app/public/server.py`, `app/public/publication.py`, `app/public/queries.py`, `app/public/models.py` (delete if unused), `app/dashboard/server.py`, `app/regime/run.py`, `tests/public/test_public_v2.py`, `tests/public/test_release.py`, `tests/public/test_explanations.py`, `tests/dashboard/test_dashboard.py`, `docs/public-release.md` (server command), `docs/reasoning/RUNTIME.md:158-159` (public db path), `README.md` (one sentence), `plans/README.md`.
- Create: `docs/archive/README.md`, `plans/archive/README.md`; move `plans/001-*.md` … `plans/031-*.md` and `plans/HUMAN_GUIDE.md` into `plans/archive/`.
- Git: `git rm --cached skills-lock.json` (it is in `.gitignore` but tracked).

**Out of scope** (do NOT touch):
- `app/x/signals.py`, `app/x/posts.py`, `app/x/run.py`, `app/x/pipeline.py` — live X pipeline; labeling imported from them, not the reverse.
- Any `CREATE TABLE` in `app/storage/database.py` — the `x_*` tables hold real trial data and are used by the X pipeline; no schema change, no data deletion.
- `docs/mandate.md`, `docs/risk_policy.md`, `docs/risk_posture.md`, `docs/source_policy.md`, `docs/theme_classification.md`, `boustrategy_spec.md`, `NOTES.md`, `docs/prompts/` — maintainer-owned. (`NOTES.md:22-38` is a self-labelled stale snapshot; mention it in your report, do not edit it.)
- `docs/research/regime_backtest_v0.md` — signed-off evidence, stays.
- `DEVELOPMENT.md` narrative about labeling and replay — history, stays.
- `app/public/queries.py` functions other than the two legacy adapters; `app/public/activity.py`, `explanations.py`, `exports.py`; the v2 `legacy-decisions` route.
- `public-ui/src` — no frontend change (it never used v1).
- `data/` and the real database.

## Git workflow

- Branch: `advisor/037-retire-finished-subsystems`, from the current working branch.
- This plan makes FOUR commits in a fixed order (Steps 1, 5, 7, 9); the first is the archive snapshot and gets the tag. Commit messages are given per step.
- Do NOT push. Tags are local until the maintainer pushes them (`git push --tags` is the maintainer's call).

## Steps

### Step 1: Snapshot every file about to be retired, and tag it

The retired files must exist in a commit in their FINAL state (the working
tree carries uncommitted edits to `app/labeling/*` and `app/x/replay.py`
from the plan-031 audit; `app/public/projection.py` has never been committed).

1. `git add app/labeling tests/labeling app/x/replay.py tests/x/test_replay.py app/public/projection.py tests/public/test_public_dashboard.py`
2. Confirm `git status --short` shows ONLY those paths staged (`A`/`M` in the first column) and nothing else staged. If anything else is staged, `git restore --staged <path>` it.
3. `git commit -m "chore: snapshot labeling, replay and public v1 projector before retirement"`
4. `git tag -a archive/2026-09-retirements -m "Final state of app/labeling, app/x/replay.py and app/public/projection.py before plan 037 removed them"`

Note: `app/public/server.py`, `queries.py`, `models.py` are also
uncommitted and will be edited (not deleted) later in this plan; their pre-edit
state is NOT part of this snapshot, which is fine — the snapshot's purpose is
the three retired subsystems, and `models.py`'s v1 shapes are reconstructible
from `projection.py` in the tag.

**Verify**: `git show --stat archive/2026-09-retirements | grep -c "app/labeling\|replay\|projection\|test_public_dashboard"` → 10 or more. `git tag -l "archive/*"` → `archive/2026-09-retirements`.

### Step 2: Remove the labeling subsystem and the replay tool

1. `git rm -r app/labeling tests/labeling`
2. `git rm app/x/replay.py tests/x/test_replay.py`
3. Migrate the two X-pipeline tests that used the labeling UI as their read side
   (correction added 2026-09-08 after an executor STOP: the original sweep
   missed these). In `tests/x/test_posts.py`:
   - `test_end_to_end_fetch_stores_reply_context_and_review_ui_shows_it`
     (~line 322) and `test_end_to_end_fetch_stores_media_and_review_ui_shows_it`
     (~line 364) each run a fake fetch through `_cmd_fetch`, close the
     connection, then open `app.labeling.server.create_app(db_path)` and GET
     `/api/next` to assert `post_id`, `reply_context` and `media`.
   - Keep the fetch half unchanged. Replace the UI half: reopen the database
     with `connect(db_path)`, call `unreviewed_posts(conn)` from
     `app.x.posts` (signature `unreviewed_posts(conn, limit=50) -> list[XPost]`,
     line ~108), take the single returned post, and assert the same facts:
     `post.post_id == "42"` and `post.reply_context == "TSMC capacity is tight this quarter"`
     in the first test; `post.post_id == "43"` and
     `[m.model_dump() for m in post.media] == [{"url": ..., "media_type": "photo", "alt_text": "capacity chart"}]`
     in the second (check `MediaItem`'s field set with `MediaItem.model_fields`
     and match it exactly).
   - Rename them `test_end_to_end_fetch_stores_reply_context_readable_by_pipeline`
     and `test_end_to_end_fetch_stores_media_readable_by_pipeline`; update their
     docstrings to say the read side is the pipeline's `unreviewed_posts`, not
     the retired review UI. Remove the `TestClient` and `create_app` imports
     from both.
4. Sweep: `grep -rn "app.labeling\|app.x.replay\|labeling.server\|8377" app tests ops docs/reasoning README.md AGENTS.md start-boustrategy.cmd` → must return nothing in `app/`, `tests/`, `ops/`, `docs/reasoning/`. (Mentions in `DEVELOPMENT.md`, `docs/research/`, `docs/plan-031-audit.md`, `docs/x_manual/README.md` are history and stay.) If this sweep finds a reference NOT listed in this plan, STOP and report it.
5. Check `app/x/posts.py` and `app/x/signals.py` for names that were exported ONLY for labeling (e.g. `_media_from_row` is imported by `adjudication.py`): `grep -rn "_media_from_row" app tests`. If a function now has zero callers outside its own file AND is private (`_`-prefixed), delete it; if it is public or still used, leave it. List what you deleted in your report.

**Verify**: `python -m pytest -q` → all pass (count drops by the labeling and replay tests, ~40-50 fewer). `python -m mypy app tests` → `Success`.

### Step 3: Remove the public v1 routes and the source projector

In `app/public/server.py`:

1. Delete the two v1 route functions (Excerpt A, lines ~51-90). Keep `/api/public/v2/legacy-decisions/{ticker}/{created_at}` (~295-310).
2. Change the signature to `create_public_app(public_db_path: str | Path, frontend_dir: str | Path = "public-ui/dist") -> FastAPI`; `published = Path(public_db_path)`; delete `path` and the `with_name(...)` default. There must be no `open_readonly(path)` left.
3. Remove `projection` from the `from app.public import …` line and delete `from app.public.models import PublicDashboard, PublicDecision`.
4. `main()`: delete `--db`; make `--public-db` required; `create_public_app(args.public_db)`.
5. Update every caller: `grep -rn "create_public_app(" app tests public-ui/fixtures` and change `create_public_app(source, ..., public_db_path=public)` → `create_public_app(public, ...)`. Known sites: `tests/performance/test_reporting.py:~369`, `tests/public/benchmark_http.py:~247,257`, `tests/public/test_activity.py:~107`, `tests/public/test_explanations.py` (4 sites), `tests/public/test_public_v2.py` (many), `tests/public/test_release.py:~39`, `public-ui/fixtures/generate.py`.
6. `docs/public-release.md:70`: serve command becomes `python -m app.public.server --public-db data/boustrategy.public.db --port 8380`; adjust the sentence if it mentions `--db`. `docs/reasoning/RUNTIME.md:158-159`: change `data/public.db` to `data/boustrategy.public.db` (the two runbooks currently disagree).

In `app/public/publication.py`:

7. Move the two constants from `projection.py:24-33` into `publication.py` as module-level `_PUBLIC_LIFECYCLE` and `_PUBLIC_SOURCE_TYPES` (copy the literals exactly) and replace the three `projection._…` references (Excerpt B) with the local names.
8. Replace the projector call in the paper block (Excerpt C) with an inline computation that produces the same two values, following the algorithm in Excerpt C's bullet list exactly. Target shape:
   ```python
   paper_status, paper_equity, paper_positions = "unavailable", None, []
   # (has_paper_data / contamination check / per-position valuation / equity as specified)
   paper_view = {
       "portfolio_id": "paper", "name": "BouStrategy paper", "mode": "paper", "is_default": False,
       "status": paper_status, "reason": None, "data_as_of": None,
       "equity": paper_equity, "return_percent": None, "history": [],
       "positions": paper_positions, "cash": None,
       "capabilities": {"returns": False, "cash": False, "quantities": True},
   }
   ```
   Each position is a plain dict with keys `ticker, shares, average_cost, latest_price, market_value, weight, unrealized_return_percent, theme, latest_public_summary` (the last is `None`). Import `cash_balance` from `app.paper.broker` (check whether `publication.py` already imports from `app.paper`). Keep the existing comment's intent: paper positions are materialized only at publication, never on a v2 GET.
9. Remove `projection` from `from app.public import activity, explanations, projection`.
10. `git rm app/public/projection.py`.

In `app/public/queries.py`:

11. Delete `legacy_dashboard` and `legacy_decision` (Excerpt D, lines ~258-352) and the now-unused `from app.public.models import (...)` block. Confirm `json` and any other import used only by those two are still used elsewhere in the file (ruff will flag unused imports).
12. `grep -rn "app.public.models\|from app.public import models" app tests public-ui/fixtures` → if nothing remains, `git rm app/public/models.py`. If something remains, STOP and report the importer.

**Verify**: `python -m ruff check .` → passes (this catches every dangling import). `python -m mypy app tests` → `Success`. Tests will fail on v1 references until Step 6.

### Step 4: Delete the two dead symbols

1. `app/dashboard/server.py`: delete `render_x_snippet` (Excerpt F). In `tests/dashboard/test_dashboard.py` delete `test_x_snippet_public_switch_is_single_seam` and remove `render_x_snippet` from the import on line 10.
2. `app/regime/run.py`: delete `latest_published_regime` (lines 25-33). Then check whether `RegimeState` or `date` imports in that file became unused (ruff will tell you).

**Verify**: `python -m ruff check .` → passes. `python -m pytest -q tests/dashboard tests/regime` → pass.

### Step 5: Commit the code retirement

`git add -u app tests docs/public-release.md docs/reasoning/RUNTIME.md public-ui/fixtures/generate.py` (use `-u` so only already-tracked/staged-in-Step-1 paths are picked up; then `git status --short` and confirm nothing outside the in-scope list is staged — in particular none of the maintainer's other uncommitted `app/` files. If `-u` picked up unrelated modified files, `git restore --staged` them and stage explicitly instead.)

`git commit -m "chore: retire labeling subsystem, replay tool and public v1 path"`

Tests are still red at this point (v1 references in tests); Step 6 fixes them before the next commit.

### Step 6: Port the private-string assertions to v2, then remove v1 tests

1. Read `tests/public/test_public_dashboard.py::test_public_projection_filters_sources_ids_and_live_details` (Excerpt E) from the archive tag if you already deleted it: `git show archive/2026-09-retirements:tests/public/test_public_dashboard.py`.
2. In `tests/public/test_public_v2.py` add `test_v2_detail_never_serializes_private_source_state`: seed the same record with the same PRIVATE_* payload (internal notes, source pack id, unsafe claim, internal memo, x-signal summary, trigger subject/raw, regime private component, broker event with a `CREDENTIAL` secret), `publish(source, public)`, GET `/api/public/v2/decisions?portfolio_id=paper` to obtain the public id, GET `/api/public/v2/decisions/{public_id}` and `/api/public/v2/decisions/{public_id}/export`, and assert that none of the strings in the original test's `sensitive` list appears in either response text. Keep the exact list, including `"confidence"` and the private `decision_id`. Also assert the published FILE bytes contain none of them (`public.read_bytes()`), which is stronger than the old route-level check.
3. Delete `tests/public/test_public_dashboard.py` (`git rm`, if not already).
4. In `tests/public/test_public_v2.py`: delete `test_published_legacy_detail_uses_publication_snapshot` and `test_legacy_feeds_are_bounded_with_independent_history_counts` (v1-only). For the remaining v1 lines (43, 123, 134, 364, 413, 430-434, 533-536): replace `/api/public/v1/dashboard` status checks with the equivalent v2 call (`/api/public/v2/portfolios/paper/overview` or `/api/public/v2/decisions?portfolio_id=paper`), and replace `/api/public/v1/decisions/{ticker}/{created_at}` with `/api/public/v2/legacy-decisions/{ticker}/{created_at}`, preserving each assertion's intent (unpublished edits invisible, 404 on unknown, retraction → 410). The test named `test_published_x_usage_keeps_recorded_flags_and_hides_private_summary` (~533) checks `positions[0]["average_cost"] is None` via v1: use `/api/public/v2/portfolios/paper/positions` and assert the same fields.
5. `tests/public/test_release.py:42-43`: drop the two v1 paths from the route list; if the list would become empty or the test's intent ("built surface has no mutation routes") depends on them, substitute the v2 overview and legacy-decisions paths.
6. `tests/public/test_explanations.py:109,398`: replace with the v2 `legacy-decisions` route and `/api/public/v2/portfolios/paper/overview` respectively, keeping the assertions.
7. `tests/dashboard/test_dashboard.py` and any other file: `grep -rn "v1/" tests` → no matches.

**Verify**: `python -m pytest -q` → all pass. `python public-ui/fixtures/generate.py` (read its `main` for arguments) → `git diff --stat public-ui/fixtures/public-v2.json` shows no change. `npm --prefix public-ui run test` → 26 pass.

### Step 7: Commit the test migration

`git add tests public-ui/fixtures` (then confirm with `git status --short` that only test/fixture paths are staged) and `git commit -m "test: move public coverage to v2 routes and published-file assertions"`.

### Step 8: Write the retirement ledger and archive the plan history

1. Create `docs/archive/README.md` with this structure (fill every field from the facts in this plan; no placeholders):

   ```markdown
   # Retired subsystems

   Code removed from the tree but preserved in git. Each entry gives the
   restore command; the tag `archive/2026-09-retirements` holds the final
   state of every file listed here. To browse without restoring:
   `git show archive/2026-09-retirements:<path>`.

   ## Labeling subsystem (retired 2026-09-<day>, plan 037)
   - What: local review inbox (`python -m app.labeling.server`, port 8377), gate-agreement experiment harness (`app/labeling/experiment.py`), adjudication UI (`app/labeling/adjudication.py`), and their tests.
   - Why: maintainer decision 2026-07-15 (plans/archive/README.md, "No ongoing manual labeling"); the gate experiment completed (Luna 72.5% raw agreement over 1,761 posts; docs/research/gate_experiment_findings.md).
   - Data kept: source-db tables x_posts, x_signals, x_gate_predictions, x_adjudications, x_score_snapshots — untouched; the X pipeline still uses x_posts/x_signals.
   - History: DEVELOPMENT.md "Learning what a useful X feed looks like"; plans/archive/011-, 015-, 016-.
   - Restore: `git checkout archive/2026-09-retirements -- app/labeling tests/labeling` (then reinstall nothing; it has no extra dependencies).

   ## X replay study tool (retired …)
   - What / Why / History (DEVELOPMENT.md "Replaying the old data…") / Restore: `git checkout archive/2026-09-retirements -- app/x/replay.py tests/x/test_replay.py`.

   ## Public API v1 and source projector (retired …)
   - What: `/api/public/v1/dashboard`, `/api/public/v1/decisions/{ticker}/{created_at}`, `app/public/projection.py`, `legacy_dashboard`/`legacy_decision`, `app/public/models.py`.
   - Why: never published; superseded by v2 over the published store; old links resolve via `/api/public/v2/legacy-decisions/{ticker}/{created_at}`.
   - Restore: `git checkout archive/2026-09-retirements -- app/public/projection.py tests/public/test_public_dashboard.py` (routes and adapters: `git show <commit before "chore: retire …">:app/public/server.py`).
   ```

2. Create `plans/archive/` and `git mv` every existing `plans/0NN-*.md` numbered 001-031 (30 files; plan 017 has no file) plus `plans/HUMAN_GUIDE.md` into it.
3. Create `plans/archive/README.md` by MOVING these sections out of `plans/README.md` verbatim: the 001-030 status table and its preamble (`## Execution order & status`, lines ~29-74), `## Dependency notes` (105-130), `## Direction items not yet planned` (371-434), `## Findings considered and rejected` (435-448), `## Not audited (2026-06-12 run)` (449-454), and `## Public product planning, September 5, 2026` (455-487). Prefix the file with one paragraph: "Completed plans 001-031 and the audit history that produced them. The live index is ../README.md. Maintainer decisions remain in the live index because they still govern the code."
4. Rewrite `plans/README.md` to contain, in order: the header paragraph (updated: "Originally generated … ; history archived 2026-09-<day> in archive/"), the source-of-truth note, `## Baseline rule for executors`, `## Human checkpoints`, `## Maintainer decisions (resolved)` (unchanged, verbatim), then the 2026-09-08 advisor section with its live table (032-037) as the ONLY status table, its backlog, rejections and not-audited lists. Replace the `HUMAN_GUIDE.md` pointer at lines 9-11 with "Completed plans and the original human guide live in [archive/](archive/README.md)." Add a row for 037 to the live table.
5. `README.md:37-38`: replace "A separate public-facing dashboard will eventually present public-safe account performance and agent reasoning." with "The public dashboard (`app/public/`, `public-ui/`) is documented in [docs/public-release.md](docs/public-release.md). Retired subsystems are listed in [docs/archive/README.md](docs/archive/README.md)."
6. `git rm --cached skills-lock.json` (it is gitignored at `.gitignore:11` but still tracked).

**Verify**: `ls plans` → `032-…`, `033-…`, `034-…`, `035-…`, `036-…`, `037-…`, `README.md`, `archive/`. `ls plans/archive | wc -l` → 32 (30 plan files — there is no `017-*.md`, plan 017 was a micro-fix recorded only in the index table — plus HUMAN_GUIDE.md and the new archive README). `grep -c "^| 0[0-3][0-9] " plans/README.md` → 6 (032-037 only). `git ls-files skills-lock.json` → empty. `grep -rn "HUMAN_GUIDE" plans/README.md` → only the archive pointer.

### Step 9: Commit docs and archive, run every gate

`git add docs/archive plans README.md .` — NO: stage explicitly: `git add docs/archive/README.md plans README.md` and `git rm --cached skills-lock.json` is already staged. `git status --short` must show only those plus the renames. Then:

`git commit -m "docs: archive completed plans and record retired subsystems"`

Run all commands in the Commands table, including the dead-reference sweep; the sweep must show only the historical mentions listed there.

## Test plan

- New: `tests/public/test_public_v2.py::test_v2_detail_never_serializes_private_source_state` (ported from the deleted v1 test, strengthened with a published-file bytes check).
- Migrated: every v1 assertion in `test_public_v2.py`, `test_release.py`, `test_explanations.py` now targets v2 or `legacy-decisions`.
- Deleted: `tests/labeling/*`, `tests/x/test_replay.py`, `tests/public/test_public_dashboard.py`, `test_x_snippet_public_switch_is_single_seam`, two v1-only v2 tests.
- Verification: `python -m pytest -q` → all pass (expect roughly 445-460 tests instead of 506); `npm --prefix public-ui run test` → 26 pass; fixture generator output unchanged.

## Done criteria

- [ ] `git tag -l archive/2026-09-retirements` → present, pointing at the Step 1 snapshot commit
- [ ] `test -d app/labeling || echo gone` → `gone`; same for `tests/labeling`, `app/x/replay.py`, `app/public/projection.py`, `tests/public/test_public_dashboard.py`
- [ ] `grep -rn "/api/public/v1" app tests public-ui/src public-ui/fixtures` → no matches
- [ ] `grep -rn "render_x_snippet\|latest_published_regime\|legacy_dashboard\|legacy_decision" app tests` → no matches
- [ ] `grep -n "_PUBLIC_LIFECYCLE\|_PUBLIC_SOURCE_TYPES" app/public/publication.py` → definitions present, no `projection.` prefix anywhere in `app/public`
- [ ] `docs/archive/README.md` exists with three entries, each with a working `git checkout archive/2026-09-retirements -- …` line
- [ ] `ls plans/archive | wc -l` → 32 (no `017-*.md` exists); live `plans/README.md` table lists 032-037 only and still contains `## Maintainer decisions (resolved)` verbatim
- [ ] `git ls-files skills-lock.json` → empty
- [ ] `python -m pytest -q`, `python -m ruff check .`, `python -m ruff format --check .`, `python -m mypy app tests`, `npm --prefix public-ui run test` all exit 0
- [ ] `git diff --stat public-ui/fixtures/public-v2.json` after regenerating → empty
- [ ] Exactly four new commits on the branch; `git status --short` shows only the maintainer's pre-existing uncommitted paths (none of which you staged)
- [ ] `plans/README.md` status row for 037 updated

## STOP conditions

Stop and report back if:

- Any excerpt does not match the live file.
- `app/` contains an importer of `app.labeling` or `app.x.replay` (none exist at planning time).
- After Step 3.12 something still imports `app.public.models` (report the importer; do not keep `models.py` "just in case").
- The paper view materialized in Step 3.8 produces a different `positions`/`status`/`equity` than before for the same source db — check by running `tests/public/test_public_v2.py` and `tests/performance/test_reporting.py`; if a paper-view assertion fails, compare against `git show archive/2026-09-retirements:app/public/projection.py` and report the divergence rather than loosening the test.
- The fixture generator's output changes (`public-v2.json` diff non-empty) — the React tests depend on it; report the diff.
- `git status` shows one of the maintainer's unrelated uncommitted files staged and you cannot cleanly unstage it.
- You are tempted to touch any `CREATE TABLE` in `app/storage/database.py` or any row in `data/`.

## Maintenance notes

- The retirement ledger `docs/archive/README.md` is the discoverable trace the maintainer asked for. Any future removal of a subsystem adds an entry there and a new `archive/<yyyy-mm>-<topic>` tag; never delete without both.
- The archive tag is local until the maintainer runs `git push --tags`; remind them in the report (pushing needs their explicit approval).
- `x_*` tables remain in the schema even though the labeling UI is gone; the X pipeline and future relevance-gate work read them. If the maintainer ever decides to drop `x_gate_predictions`/`x_adjudications`/`x_score_snapshots`, that is a deliberate data migration with a backup, not a cleanup.
- Deferred, not done here: `NOTES.md:22-38` stale snapshot (maintainer-owned file); `docs/theme_classification.md` (explicitly retained as inactive by `boustrategy_spec.md:131`); the `tests/public/benchmark_*.py` relocation; moving `table_exists` out of `app/dashboard/queries.py` (still imported by `app/public/*`, which is why the public package retains one import edge into the private dashboard package).
- Reviewer focus: the Step 3.8 paper materialization must be a faithful transliteration of `projection.py:121-186` minus the decision-summary lookup; and the four commits must contain no files outside this plan's scope.
