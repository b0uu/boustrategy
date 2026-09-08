# Plan 035: Make the private operator view count decisions from the link table for retried runs, and remove the dead retry bypass

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 40b317b..HEAD -- app/reason/run.py app/dashboard/queries.py app/triggers/store.py`
> plus manual comparison for UNTRACKED `app/dashboard/views.py` and
> `app/storage/runtime.py` (compare excerpts with `sed -n '<start>,<end>p'`).
> On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `40b317b`; every excerpt re-verified against the tree at `0702ddd` (after plan 037) on 2026-09-08

## Why this matters

A live reasoning run has two records: the legacy `reasoning_runs` row (the
prepared run the operator hands to the model) and one or more
`runtime_attempts` rows (the persisted runtime's attempts against it). By
deliberate design — pinned by
`tests/reason/test_runtime.py::test_live_attempt_rechecks_snapshot_after_authoring_and_preserves_failed_retry`
— the legacy row is completed exactly once, by the FIRST attempt, and never
rewritten: after a failed first attempt it reads `result = FAILED` with that
attempt's `decision_ids`, and a later successful retry links its decisions only
through the `reasoning_run_decisions` table. The public publisher already joins
the link table, so the public side is correct, and the private operator page
already shows the latest attempt's status in its "Run" metric.

What is still wrong on the operator page:

- The **Decisions** metric is `len(run_json["decision_ids"])` from the legacy
  row, so after a successful retry it shows the failed first attempt's count
  (typically 0) while a live order intent exists.
- The **Run** status shown is `attempts[0]["status"]`, the latest attempt for
  the *profile*, not for the displayed run. With one run per session that
  coincides today; it will silently disagree the first time a profile has a
  manual run and a scheduled run on the same day.

Two loose ends in the submission path: `submit_decision` passes
`runtime_retry=runtime_attempt_id is not None` — true for EVERY runtime
submission, not just retries — which disables the "reasoning run is not
PREPARED" guard under a misleading name; and `_submit_decision` carries a
`consume_trigger_ids` branch that no caller reaches, whose `mark_triggers` call
would commit mid-transaction if it ever were reached.

After this plan: the operator page counts decisions from the link table and
derives run status from the attempts of the displayed run; the guard has an
honest name; the dead branch is gone.

## Current state

Files and roles:

- `app/dashboard/queries.py` — `live_operator_status(...)` (defined at line 518) builds the operator payload per profile; the run block is at lines 544-567 and the attempts block at 674-705.
- `app/dashboard/views.py` — renders it (`displayed_run_status` at ~801-803; the "Run"/"Decisions" metrics at ~846-847; the comparison table at ~884-886).
- `app/storage/runtime.py` — `finish()` completes the legacy run only while still `PREPARED` (lines ~305-332). BY DESIGN; do not change.
- `app/reason/run.py` — `process_decision(..., runtime_retry: bool = False)` at ~195-220; `_submit_decision` ends at ~348-350; `submit_decision` at ~354-416.
- `app/triggers/store.py:51` — `mark_triggers` calls `conn.commit()` unconditionally.
- `tests/dashboard/test_live_operator.py` — exemplar; `test_private_operator_reports_actual_runtime_attempt` (line 322) seeds attempts and asserts on the payload.
- `tests/reason/test_runtime.py` — `live_run(conn, folder)` helper (line 372) and the retry test above (line 422) build exactly the state this plan renders.

### Excerpt A — `app/dashboard/queries.py:544-567` (legacy run copied into the payload)

```python
        run_row = (
            conn.execute(
                """
                SELECT run_json FROM reasoning_runs
                WHERE execution_profile_id = ? AND session_date = ? AND slot = ?
                ORDER BY started_at DESC, reasoning_run_id DESC LIMIT 1
                """,
                (profile_id, shared["session_date"], shared["slot"]),
            ).fetchone()
            if shared
            else None
        )
        run = None
        if run_row is not None:
            run_json = json.loads(run_row[0])
            run = {
                "reasoning_run_id": run_json["reasoning_run_id"],
                "portfolio_snapshot_id": run_json["portfolio_snapshot_id"],
                "shared_bundle_path": run_json["shared_bundle_path"],
                "shared_bundle_sha256": run_json["shared_bundle_sha256"],
                "result": run_json["result"],
                "public_summary": run_json["public_summary"],
                "decision_count": len(run_json["decision_ids"]),
            }
```

### Excerpt B — `app/dashboard/queries.py:674-705` (existing attempt block)

```python
        attempts = (
            selected_rows(
                conn,
                "SELECT a.attempt_id, a.status, a.stage, a.started_at, a.heartbeat_at, "
                "a.finished_at, a.reason, r.reasoning_run_id FROM runtime_attempts a "
                "JOIN runtime_runs r USING(run_id) "
                "WHERE r.execution_profile_id=? ORDER BY julianday(a.started_at) DESC LIMIT 20",
                (profile_id,),
            )
            if table_exists(conn, "runtime_attempts")
            else []
        )
        ...
        profile_rows.append(
            {
                ...
                "run": run,
                "runtime_attempts": attempts,
                "runtime_status": attempts[0]["status"] if attempts else None,
```

Each attempt row already carries `reasoning_run_id`, so the per-run attempt can
be selected in Python from `attempts` without a new query.

### Excerpt C — `app/dashboard/views.py:801-803` and `:846-847`

```python
        displayed_run_status = profile.get("runtime_status") or (
            run["result"] if run else "unavailable"
        )
```

```python
            f"<div><div class='metric-label'>Run</div><div class='metric-value'>{escape(displayed_run_status)}</div></div>"
            f"<div><div class='metric-label'>Decisions</div><div class='metric-value'>{run['decision_count'] if run else 0}</div></div>"
```

The same `displayed_run_status` and `run["decision_count"]` feed the comparison
table at ~884-886. `escape` is `html.escape` imported at the top of `views.py`.

### Excerpt D — `app/reason/run.py:219-220` (the guard) and `:401` (the caller)

```python
        if run.result != ReasoningRunResult.PREPARED and not runtime_retry:
            raise ValueError("reasoning run is not PREPARED")
```

```python
            runtime_retry=runtime_attempt_id is not None,
```

The runtime path has its own identity binding (`validate_fence` and the
`runtime submission identity mismatch` check at `run.py:~372-382`), so the
legacy `PREPARED` guard is genuinely irrelevant for runtime submissions; only
the name is wrong.

### Excerpt E — `app/reason/run.py:348-350` (dead branch at the end of `_submit_decision`)

```python
    if consume_trigger_ids and outcome.final_status in _CONSIDERED_STATUSES:
        mark_triggers(conn, consume_trigger_ids, "consumed")
    return outcome
```

`submit_decision` never forwards `consume_trigger_ids` to `_submit_decision`
(its call at `run.py:~384-402` passes `record_data, on_date` and keyword
arguments only); it consumes triggers itself at `run.py:~414-415` AFTER the
`immediate(conn)` block commits. `_submit_decision` runs inside that block, and
`mark_triggers` commits unconditionally, so the dead branch would break the
transaction if ever reached.

### Repo conventions that apply

- AGENTS.md: crash early; no single-use helpers; comments only for non-obvious business logic.
- `live_operator` degrades gracefully on missing tables via `table_exists(...)`; match that for any new query.
- Every dynamic value in `views.py` goes through `escape(...)`; `test_live_operator.py:184` asserts private state is escaped.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Dashboard tests | `python -m pytest -q tests/dashboard` | all pass |
| Reason tests | `python -m pytest -q tests/reason` | all pass |
| Full tests | `python -m pytest -q` | all pass |
| Lint | `python -m ruff check .` | `All checks passed!` |
| Format | `python -m ruff format --check .` | `N files already formatted` |
| Types | `python -m mypy app tests` | `Success: no issues found` |

## Scope

**In scope**:
- `app/dashboard/queries.py` (the `live_operator` run block and the `runtime_status` line only)
- `app/reason/run.py` (rename the parameter; delete the dead branch)
- `tests/dashboard/test_live_operator.py` (add one test)
- `tests/reason/test_live_submit.py` (only if it references `runtime_retry`)

**Out of scope**:
- `app/dashboard/views.py` — keep payload key names so no rendering change is needed. If you find you must change the view, STOP and report.
- `app/storage/runtime.py` `finish()` and `app/storage/records.py` `complete_reasoning_run` — once-only legacy completion is by design.
- `app/triggers/store.py` — with the dead branch gone there is no in-transaction caller.
- `app/public/**` — publication already joins the link table.
- `tests/reason/test_runtime.py::test_live_attempt_rechecks_snapshot_after_authoring_and_preserves_failed_retry` — must keep passing unchanged.

## Git workflow

- Branch: `advisor/035-operator-view-attempt-truth`, from the current working branch. Stage only in-scope paths with `git add <path>`; never `git add -A` (the tree has a large uncommitted delta that is not yours).
- Commit style: `fix: count operator decisions from linked records`.
- Do NOT push.

## Steps

### Step 1: Count decisions from the link table

In `app/dashboard/queries.py` (Excerpt A), when `run` is built, replace
`"decision_count": len(run_json["decision_ids"])` with the linked count:

```python
"decision_count": conn.execute(
    "SELECT COUNT(*) FROM reasoning_run_decisions WHERE reasoning_run_id = ?",
    (run_json["reasoning_run_id"],),
).fetchone()[0]
if table_exists(conn, "reasoning_run_decisions")
else len(run_json["decision_ids"]),
```

Add a one-line comment: the legacy row's `decision_ids` is frozen by the first
attempt; retries link additional decisions only through this table.

**Verify**: `python -m pytest -q tests/dashboard` → existing tests pass.

### Step 2: Derive the run status from the displayed run's own attempts

In the `profile_rows.append` dict (Excerpt B), replace
`"runtime_status": attempts[0]["status"] if attempts else None` with the status
of the latest attempt whose `reasoning_run_id` equals `run["reasoning_run_id"]`
when `run` exists, falling back to `attempts[0]["status"]` when there is no
`run`, and `None` when there are no attempts. `attempts` is already ordered
newest-first, so the first matching row is the latest. Inline it (a generator
expression with `next(..., None)` is fine); no helper.

**Verify**: `python -m pytest -q tests/dashboard/test_live_operator.py` → passes (the existing attempt test at line 322 seeds a runtime run whose `reasoning_run_id` equals the displayed legacy run's id, so `runtime_status` stays `no_action`).

### Step 3: Test the retried-run display

In `tests/dashboard/test_live_operator.py` add
`test_operator_view_counts_linked_decisions_after_successful_retry`, modeled on
`test_private_operator_reports_actual_runtime_attempt` (line 322) for the
query/render calls and on
`tests/reason/test_runtime.py::test_live_attempt_rechecks_snapshot_after_authoring_and_preserves_failed_retry`
(line 422) for producing the state:

- Arrange: reuse `live_run`, `save_run`, `execute_attempt` with a first runner that fails (`"submission_blocked"` branch of that test) and a retry runner that succeeds, exactly as the pinned test does. Import `live_run`, `NOW` from `tests.reason.test_runtime` and `_profile` from `tests.reason.test_live_submit` the way other tests already do (`tests/reason/test_scheduler.py:14`).
- Act: call `live_operator_status(conn, public_profile_status(load_live_profiles(config_path)), now=...)` exactly as the exemplar does (its imports: `load_live_profiles, public_profile_status` from `app.broker.config`; `live_operator_status` from `app.dashboard.queries`; `create_app` from `app.dashboard.server`), and GET `/operate/live` through `TestClient(create_app(db, live_config_path=config_path))`. Prefer building the failed-then-retried state with the operator test's own `_config`/`_populate` helpers plus `execute_attempt`; if you instead reuse `live_run` from `tests.reason.test_runtime` and `_profile` from `tests.reason.test_live_submit`, first confirm they use the same `execution_profile_id` (`codex`) and `broker_account_fingerprint` as `_config`, and STOP if they differ.
- Assert: for the codex profile, `run["result"] == "FAILED"` (legacy fact, unchanged), `run["decision_count"]` equals the row count of `reasoning_run_decisions` for that run (2 for the `submission_blocked` variant), `runtime_status == "completed"`; and the rendered HTML's Decisions metric shows that count.

**Verify**: `python -m pytest -q tests/dashboard` → passes including the new test.

### Step 4: Rename the guard bypass and delete the dead trigger branch

In `app/reason/run.py`:

1. Rename the `process_decision` parameter `runtime_retry` to `runtime_bound` (Excerpt D) and update the single caller in `submit_decision` to `runtime_bound=runtime_attempt_id is not None`. Add a one-line comment at the guard: runtime submissions are bound to their attempt by `validate_fence` and the identity check in `submit_decision`, so the legacy PREPARED guard applies only to manual submissions.
2. Delete the `consume_trigger_ids` parameter and the branch at the end of `_submit_decision` (Excerpt E). Update its signature. `grep -rn "_submit_decision(" app tests` must show no caller passing `consume_trigger_ids`.
3. `grep -rn "runtime_retry" app tests` → must return nothing.
4. If `mark_triggers` is no longer imported anywhere in `run.py` besides `submit_decision`, leave the import (it is still used there).

**Verify**: `python -m pytest -q tests/reason` → all pass. `python -m mypy app tests` → `Success`.

### Step 5: Full gates

Run every command in the table; `git status --short` shows only in-scope files.

## Test plan

- `tests/dashboard/test_live_operator.py`: after a failed first attempt and a successful retry, the operator payload counts linked decisions and reports the run's own latest attempt status; legacy `result` stays `FAILED`.
- `tests/reason/test_runtime.py` retry tests pass unchanged.
- Verification: `python -m pytest -q` → all pass, 1 new test.

## Done criteria

- [ ] `grep -rn "runtime_retry" app tests` → no matches
- [ ] `grep -n "consume_trigger_ids" app/reason/run.py` → no match inside `_submit_decision`
- [ ] `grep -n "reasoning_run_decisions" app/dashboard/queries.py` → includes the new count query
- [ ] `python -m pytest -q` exits 0 with the new test present
- [ ] `python -m ruff check .`, `python -m ruff format --check .`, `python -m mypy app tests` exit 0
- [ ] `git status --short` shows no changes outside the in-scope list
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:

- Any excerpt does not match the live file.
- `_submit_decision` has a caller that passes `consume_trigger_ids` (the branch is live and the mid-transaction commit is a real bug to plan separately).
- The pinned retry test in `tests/reason/test_runtime.py` fails after your change.
- The existing operator test at `test_live_operator.py:322` fails after Step 2. It should not: its `_populate` helper (line 57) saves a reasoning run named `rr_2026-08-27_close_{profile}` per profile and the test seeds `runtime_runs` with `reasoning_run_id='rr_2026-08-27_close_codex'`, so the per-run match finds the same attempt. If it fails anyway, report the seeded shape rather than loosening the match.

## Maintenance notes

- The legacy `reasoning_runs.result`/`decision_ids` are first-attempt facts, not run-level truth. Any new consumer of run status must join `runtime_attempts`/`reasoning_run_decisions`, as publication and now the operator view do. Worth one sentence in `docs/reasoning/RUNTIME.md` when that doc is next edited.
- If the maintainer later decides the legacy row SHOULD reflect retries, that is a deliberate change to `finish()` and `complete_reasoning_run`'s immutability contract plus the pinned test; do not drift into it.
- Reviewer focus: the new count query is guarded by `table_exists`; `runtime_status` is per-run, not per-profile.
