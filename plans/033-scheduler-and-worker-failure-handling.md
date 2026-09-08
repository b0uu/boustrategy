# Plan 033: Keep the scheduled runtime alive across ET-midnight grace windows and runner cleanup failures

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: the in-scope files under `app/reason/` and
> `app/storage/` are UNTRACKED in git at the time of writing (uncommitted
> work), so `git diff` cannot detect drift. Compare every "Current state"
> excerpt below against the live file with `sed -n '<start>,<end>p' <file>`.
> On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `40b317b` (branch `advisor/030-private-dual-agent-dashboard`, working tree uncommitted), 2026-09-08

## Why this matters

The scheduled reasoning runtime is a one-shot command (`python -m app.reason.runtime scheduled`)
that a host supervisor is meant to invoke every minute. It must therefore be
robust to two things a supervisor cannot fix: an occurrence that becomes due late
in the evening whose grace window crosses ET midnight, and a model subprocess
whose cleanup does not finish cleanly. Today both produce an unhandled exception
with no persisted reason:

1. **Midnight grace window.** `record_due` returns an occurrence for session day
   D as "ready" as long as `now <= due + grace_seconds`, even when `now` is
   already on ET day D+1. The scheduler then builds a run with
   `session_date=D`, `prepared_at=now`, and `save_run` rejects it with
   "prepared run session does not match local preparation day". That
   `ValueError` is not caught in `execute_due`, so the entire batch aborts,
   the occurrence stays `waiting`, and every subsequent per-minute invocation
   re-crashes until grace finally expires. `grace_seconds` is allowed up to
   86400, so this is reachable from configuration alone (for example a late
   `due_local` with a multi-hour grace, or the default 17:45 close slot with a
   grace over 6h15m).
2. **Runner cleanup.** In `run_codex`, the `finally` block calls
   `process.wait(timeout=10)` (which raises `subprocess.TimeoutExpired`) and
   raises `RunnerFailure("subprocess_pipe_cleanup_failed")` if a drain thread
   is still alive. `execute_attempt` catches only `LeaseLost`, `RunnerFailure`,
   `ValidationError`, `ValueError`, `OSError` — `TimeoutExpired` is none of
   those, so the attempt row is never finished and stays `running` until the
   lease expires; meanwhile the raise inside `finally` replaces whatever
   exception was already propagating (a timeout, a cancellation) so the real
   cause is lost. And `subprocess_pipe_cleanup_failed` is missing from the
   worker's reason map, so it is recorded as `submission_blocked`, which on a
   money path is materially misleading.

After this plan: an occurrence whose ET day has passed is recorded as
`skipped/grace_expired` instead of crashing the batch; a cleanup failure never
masks the original error, always finishes the attempt, and is recorded under
its own reason.

## Current state

Files and roles:

- `app/storage/schedules.py` — schedule revisions, occurrences; `record_due(conn, schedule_id, now)` decides which occurrences are ready.
- `app/reason/scheduler.py` — `execute_due(...)`: for each ready occurrence, checks dependencies, builds a `RuntimeRun`, assembles intake, runs `execute_attempt`.
- `app/storage/runtime.py` — `save_run`, `claim`, `heartbeat`, `finish`, `expire`, the `immediate()` transaction helper, and the `LeaseLost` exception.
- `app/reason/worker.py` — `execute_attempt(...)`: claims, runs the runner, submits decisions, finishes the attempt; maps failures to `(status, reason)`.
- `app/reason/codex_runner.py` — `run_codex(...)`: spawns the Codex CLI, drains pipes on threads, enforces timeout/cancel, cleans up in `finally`.
- `app/schemas/runtime.py` — `ScheduleRevision` (`grace_seconds: int = Field(default=1800, ge=0, le=86400)` at line 68).
- `tests/reason/test_scheduler.py` — exemplar tests for `execute_due` (see Excerpt F).
- `tests/reason/test_codex_runner.py` — exemplar tests that run a real local fake process.
- `tests/reason/test_runtime.py` — `NOW = datetime(2026, 6, 10, 21, 45, tzinfo=UTC)` (a Wednesday, 17:45 ET) and `paper_run(...)` helper reused by other tests.

### Excerpt A — `app/storage/schedules.py:198-232` (`record_due` body)

```python
        ready = []
        while day <= now.astimezone(NEW_YORK).date():
            due = due_at(schedule, day)
            if due is not None and schedule.configured_at <= due <= now:
                expired = now > due + timedelta(seconds=schedule.grace_seconds)
                identity = "occ_" + uuid4().hex
                conn.execute(
                    "INSERT OR IGNORE INTO schedule_occurrences VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        identity,
                        "occ_" + uuid4().hex,
                        schedule_id,
                        schedule.revision,
                        day.isoformat(),
                        due.isoformat(),
                        "skipped" if expired else "waiting",
                        "grace_expired" if expired else None,
                        now.isoformat(),
                    ),
                )
                row = conn.execute(
                    "SELECT occurrence_id, status FROM schedule_occurrences WHERE "
                    "schedule_id=? AND session_date=?",
                    (schedule_id, day.isoformat()),
                ).fetchone()
                if row[1] == "waiting":
                    if expired:
                        conn.execute(
                            "UPDATE schedule_occurrences SET status='skipped', "
                            "reason='grace_expired', observed_at=? WHERE occurrence_id=?",
                            (now.isoformat(), row[0]),
                        )
                    else:
                        ready.append(row[0])
            day += timedelta(days=1)
        return ready
```

### Excerpt B — `app/storage/runtime.py:37-41` (`save_run` session check)

```python
def save_run(conn: sqlite3.Connection, run: RuntimeRun) -> str:
    if not is_session(run.session_date) and run.origin == "scheduled":
        raise ValueError("reasoning run requires an eligible session")
    if run.prepared_at.astimezone(NEW_YORK).date() != run.session_date:
        raise ValueError("prepared run session does not match local preparation day")
```

`claim()` at `app/storage/runtime.py:~185` has the matching check
`if run.session_date != now.astimezone(NEW_YORK).date(): raise ValueError("prepared_session_stale")`.

### Excerpt C — `app/reason/scheduler.py:119-147` (run construction, no ValueError handling)

```python
        run = RuntimeRun(
            run_id="runtime_" + uuid4().hex,
            mode=schedule.mode,
            account_id=schedule.account_id,
            execution_profile_id=schedule.execution_profile_id,
            session_date=day,
            slot=schedule.slot,
            prepared_at=now,
            intake_path=str(intake.resolve()),
            intake_sha256=checksum,
            reasoning_run_id=legacy_id,
            occurrence_id=occurrence,
            origin="scheduled",
        )
        existing = conn.execute(
            "SELECT run_json FROM runtime_runs WHERE occurrence_id=?", (occurrence,)
        ).fetchone()
        if existing:
            prepared = RuntimeRun.model_validate_json(existing[0])
        else:
            try:
                prepared = assemble_intake(conn, run, output_dir, profile)
            except sqlite3.IntegrityError:
                winner = conn.execute(
                    "SELECT run_json FROM runtime_runs WHERE occurrence_id=?", (occurrence,)
                ).fetchone()
                if winner is None:
                    raise
                prepared = RuntimeRun.model_validate_json(winner[0])
```

`assemble_intake` (`app/reason/runtime_prepare.py:269`) calls `save_run(conn, prepared)`.

The dependency-check block earlier in the same loop (`scheduler.py:~58-101`)
shows the established pattern for recording a non-fatal outcome: a `try` over
the checks, `except (OSError, ValueError)`, a diagnostic file under `log_root`,
then `with immediate(conn): UPDATE schedule_occurrences SET reason=..., observed_at=... WHERE occurrence_id=? AND status='waiting'`,
`outcomes.append({...})`, `continue`.

### Excerpt D — `app/reason/codex_runner.py:219-236` (the `finally` block)

```python
        finally:
            if tree is not None:
                tree.close()
            elif sys.platform != "win32":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)
            for reader in readers:
                reader.join(timeout=10)
                if reader.is_alive():
                    raise RunnerFailure("subprocess_pipe_cleanup_failed")
            prompt_stream.close()
        if reader_errors:
            raise RunnerFailure("log_write_failed") from reader_errors[0]
```

`RunnerFailure(ValueError)` is defined at `codex_runner.py:24`.

### Excerpt E — `app/reason/worker.py:169-211` (failure mapping)

```python
    except LeaseLost:
        with immediate(conn):
            expire(conn, clock())
        return get_attempt(conn, attempt.attempt_id)
    except (RunnerFailure, ValidationError, ValueError, OSError) as error:
        diagnostic = log_root / attempt.attempt_id
        ...
        code = (
            "snapshot_stale"
            if str(error) == "portfolio snapshot is stale"
            else str(error)
            if isinstance(error, RunnerFailure)
            or str(error)
            in {"snapshot_stale", "regime_missing", "regime_stale", "calendar_out_of_coverage"}
            else "invalid_output"
            if isinstance(error, ValidationError)
            else "submission_blocked"
        )
        reasons: dict[str, Any] = {
            "runner_timeout": ("timed_out", "runner_timeout"),
            "runner_canceled": ("canceled", "operator_canceled"),
            "runner_failed": ("failed", "runner_failed"),
            "output_too_large": ("failed", "invalid_output"),
            "invalid_output": ("failed", "invalid_output"),
            "intake_missing": ("blocked", "intake_missing"),
            "intake_changed": ("blocked", "intake_changed"),
            "intake_too_large": ("blocked", "intake_too_large"),
            "snapshot_stale": ("blocked", "snapshot_stale"),
            "regime_missing": ("blocked", "regime_missing"),
            "regime_stale": ("blocked", "regime_stale"),
            "calendar_out_of_coverage": ("blocked", "calendar_out_of_coverage"),
        }
        status, reason = reasons.get(code, ("blocked", "submission_blocked"))
        return finish(
            conn, attempt.attempt_id, attempt.fence, clock(), status=status, reason=reason
        )
```

`finish()` in `app/storage/runtime.py:~276-296` validates `reason` against a
closed `allowed_reasons` set that currently contains: `None, intake_missing,
intake_changed, intake_too_large, runner_timeout, runner_failed,
operator_canceled, invalid_output, submission_blocked, snapshot_stale,
regime_missing, regime_stale, calendar_out_of_coverage, dependency_missing`.

### Excerpt F — `tests/reason/test_scheduler.py:112-135` (exemplar)

```python
def test_missing_dependency_keeps_private_diagnostics_then_grace_skips(tmp_path: Path) -> None:
    conn = connect(tmp_path / "source.db")
    schedule = ScheduleRevision(
        schedule_id="private-close",
        revision=1,
        mode="paper",
        account_id="paper",
        schedule_mode="scheduled",
        enabled=True,
        configured_at=NOW - timedelta(hours=2),
    )
    save_schedule(conn, schedule)
    result = scheduler.execute_due(
        conn,
        schedule.schedule_id,
        "model",
        NOW,
        output_dir=tmp_path / "intakes",
        log_root=tmp_path / "logs",
        digest_dir=tmp_path / "missing",
    )
    assert result == [{"status": "waiting", "reason": "dependency_missing"}]
```

`ScheduleRevision` fields you will need: `due_local` (wall-clock ET time,
check its exact name and type in `app/schemas/runtime.py` before writing the
test) and `grace_seconds`.

### Repo conventions that apply

- AGENTS.md: crash early; catch exceptions only at real failure boundaries; never swallow; no single-use helpers; policy/reason strings are lowercase snake_case.
- Occurrence outcomes are recorded as `status` + `reason` columns on `schedule_occurrences` and echoed in the `outcomes` list returned by `execute_due`.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Runtime tests | `python -m pytest -q tests/reason` | all pass |
| Full tests | `python -m pytest -q` | all pass |
| Lint | `python -m ruff check .` | `All checks passed!` |
| Format | `python -m ruff format --check .` | `N files already formatted` |
| Types | `python -m mypy app tests` | `Success: no issues found` |

## Scope

**In scope** (the only files you should modify):
- `app/storage/schedules.py` (`record_due` only)
- `app/reason/codex_runner.py` (the `finally` block only)
- `app/reason/worker.py` (the `except` tuple and `reasons` map only)
- `app/storage/runtime.py` (the `allowed_reasons` set in `finish` only)
- `tests/reason/test_scheduler.py`, `tests/reason/test_codex_runner.py`, `tests/reason/test_runtime.py` (add tests)

**Out of scope** (do NOT touch):
- `app/reason/scheduler.py` — the fix belongs in `record_due` so that no ready occurrence can ever have a stale session; do not add a second `try/except` in the scheduler for this.
- `app/schemas/runtime.py` — do not narrow `grace_seconds`; a long grace is legitimate within a day.
- `app/reason/process_tree.py` — Windows process-tree ownership is untouched.
- Any change to lease durations, heartbeat cadence, or the `LeaseLost` path.

## Git workflow

- Branch: `advisor/033-scheduler-and-worker-failure-handling`, from the current working branch. The tree has a large uncommitted delta that is not yours: stage only in-scope paths with `git add <path>`; never `git add -A`.
- Commit style: `fix: skip occurrences whose session day has passed` / `fix: record runner cleanup failures without masking the cause`.
- Do NOT push.

## Steps

### Step 1: Treat an occurrence as grace-expired once its ET session day has passed

In `record_due` (Excerpt A), change the `expired` computation to:

```python
expired = now > due + timedelta(seconds=schedule.grace_seconds) or (
    now.astimezone(NEW_YORK).date() > day
)
```

Add a one-line comment above it explaining the invariant: a run is prepared and
claimed on its own ET session day (`save_run` and `claim` both enforce this), so
an occurrence cannot remain ready after ET midnight regardless of grace.
`NEW_YORK` is already imported in this module (it is used at line ~195).

**Verify**: `python -m pytest -q tests/reason/test_scheduler.py tests/reason/test_runtime.py` → existing tests still pass.

### Step 2: Test the midnight case end to end through `execute_due`

In `tests/reason/test_scheduler.py` add
`test_grace_window_crossing_et_midnight_skips_instead_of_crashing`, modeled on
Excerpt F:

- Arrange: a paper schedule whose `due_local` is the close slot (17:45 ET —
  check the field name and default in `app/schemas/runtime.py`) and
  `grace_seconds=8 * 3600`, `configured_at=NOW - timedelta(hours=2)`. Use
  `late = NOW + timedelta(hours=7)` (NOW is 21:45 UTC = 17:45 ET on 2026-06-10, so
  `late` is 04:45 UTC on 06-11 = 00:45 ET on 06-11: still inside grace, but past ET midnight).
- Act: `scheduler.execute_due(conn, schedule_id, "model", late, output_dir=..., log_root=..., digest_dir=tmp_path)`.
- Assert: it returns `[]` (no exception), and
  `conn.execute("SELECT session_date, status, reason FROM schedule_occurrences").fetchone() == ("2026-06-10", "skipped", "grace_expired")`,
  and `runtime_attempts` is empty.
- Also add a negative control in the same test or a second test: with
  `late = NOW + timedelta(hours=5)` (02:45 UTC = 22:45 ET, same ET day) the
  occurrence is NOT skipped for this reason (it may still be `waiting` with
  `dependency_missing` if you pass a missing digest dir — assert on that
  established outcome shape from Excerpt F).

Before writing, run the new test against the UNPATCHED `record_due` once (stash
your Step 1 change or temporarily revert it) and confirm it fails with
`ValueError: prepared run session does not match local preparation day` — that
proves the test reproduces the bug. Then restore Step 1.

**Verify**: `python -m pytest -q tests/reason/test_scheduler.py` → passes including the new test.

### Step 3: Make runner cleanup never mask the original failure

In `app/reason/codex_runner.py` (Excerpt D):

1. Introduce `cleanup_failure: RunnerFailure | None = None` immediately before the `try:` that precedes the `finally` (the `try:` at line ~202 that starts with `if sys.platform == "win32":`).
2. Inside `finally`, wrap `process.wait(timeout=10)` so a `subprocess.TimeoutExpired` sets `cleanup_failure = RunnerFailure("subprocess_pipe_cleanup_failed")` instead of propagating. Replace `raise RunnerFailure("subprocess_pipe_cleanup_failed")` inside the reader loop with the same assignment (do not `break`; keep joining the other reader). Keep `prompt_stream.close()` as the last statement of `finally`.
3. Immediately after the `finally` block (before the existing `if reader_errors:` check) add `if cleanup_failure is not None: raise cleanup_failure`. Because this is outside `finally`, an exception that was already propagating from the `try` body (timeout, cancel, `runner_failed`) wins, and the cleanup failure surfaces only when the body completed.

Note on Python semantics: raising inside `finally` replaces the in-flight
exception; that is exactly what this step removes.

**Verify**: `python -m pytest -q tests/reason/test_codex_runner.py` → existing tests pass.

### Step 4: Give the cleanup failure its own terminal reason and handle it in the worker

1. In `app/storage/runtime.py`, add `"subprocess_pipe_cleanup_failed"` to `allowed_reasons` in `finish()`.
2. In `app/reason/worker.py` (Excerpt E), add `"subprocess_pipe_cleanup_failed": ("failed", "subprocess_pipe_cleanup_failed"),` to `reasons`, and add `"log_write_failed": ("failed", "runner_failed"),` so that existing `RunnerFailure("log_write_failed")` no longer falls through to `submission_blocked` either.
3. Extend the worker's handled tuple to `(RunnerFailure, ValidationError, ValueError, OSError, subprocess.SubprocessError)` and `import subprocess` at the top of `worker.py`. This is the failure boundary for the child process (AGENTS.md convention 1 permits it); with Step 3 in place the runner should no longer leak `TimeoutExpired`, so this is defense at the boundary, not a swallow — the failure is still recorded and the attempt finished.
4. Check `app/schemas/runtime.py` for a `Literal`/enum listing attempt reasons (`grep -n "runner_timeout" app/schemas/runtime.py app/dashboard app/public`). If a closed list of reasons exists in a schema or in the public projection, add the new value there too; if that list is in a file outside the in-scope list, STOP and report which file.

**Verify**: `python -m mypy app tests` → `Success`.

### Step 5: Test the cleanup path

In `tests/reason/test_codex_runner.py`, model on
`test_runner_timeout_and_cancel_stop_real_local_process` (line 72), which
launches a real local fake executable. Add
`test_cleanup_failure_does_not_mask_runner_timeout`: monkeypatch
`subprocess.Popen.wait` (or the `process` object's `wait` via a small subclass
passed as `executable` — inspect how the existing test injects the fake process)
to raise `subprocess.TimeoutExpired(cmd="codex", timeout=10)` on the cleanup
call, run `run_codex` with a tiny `timeout_seconds`, and assert
`pytest.raises(RunnerFailure, match="runner_timeout")` — the ORIGINAL cause,
not `subprocess_pipe_cleanup_failed`.

In `tests/reason/test_runtime.py`, model on
`test_worker_partial_failure_explicit_retry_preserves_decisions_and_models`
(line 71): add `test_worker_records_cleanup_failure_and_finishes_attempt` with a
`runner` callable that raises `RunnerFailure("subprocess_pipe_cleanup_failed")`;
assert the returned attempt has `status == "failed"`,
`reason == "subprocess_pipe_cleanup_failed"`, and the lease row for the scope
has `attempt_id IS NULL` (`SELECT attempt_id FROM runtime_leases`).

**Verify**: `python -m pytest -q tests/reason` → all pass, 3-4 new tests.

### Step 6: Full gates

Run every command in the table; then `git status --short` and confirm only in-scope files changed.

## Test plan

- `tests/reason/test_scheduler.py`: midnight-crossing grace window → `skipped/grace_expired`, no exception; same-day late invocation is unaffected.
- `tests/reason/test_codex_runner.py`: cleanup `TimeoutExpired` does not mask `runner_timeout`.
- `tests/reason/test_runtime.py`: worker finishes the attempt with `failed/subprocess_pipe_cleanup_failed` and releases the lease.
- Verification: `python -m pytest -q` → all pass.

## Done criteria

- [ ] `grep -n "astimezone(NEW_YORK).date() > day" app/storage/schedules.py` → one match
- [ ] `grep -n 'raise RunnerFailure("subprocess_pipe_cleanup_failed")' app/reason/codex_runner.py` → no match inside the `finally` block (the only raise of it is after `finally`)
- [ ] `grep -n "subprocess_pipe_cleanup_failed" app/reason/worker.py app/storage/runtime.py` → one match in each
- [ ] `python -m pytest -q` exits 0 with the new tests present
- [ ] `python -m ruff check .`, `python -m ruff format --check .`, `python -m mypy app tests` exit 0
- [ ] `git status --short` shows no changes outside the in-scope list
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:

- Any "Current state" excerpt does not match the live file.
- The Step 2 test does NOT fail against the unpatched `record_due` (the reproduction is wrong; report what it did instead).
- A closed list of attempt reasons exists in a schema or projection file outside the in-scope list (Step 4.4).
- `claim()` in `app/storage/runtime.py` no longer contains the `prepared_session_stale` check — the invariant this plan relies on has changed.
- After Step 3 any existing `test_codex_runner.py` test fails twice after a reasonable fix attempt.

## Maintenance notes

- If a pre-open schedule slot is ever added whose preparation legitimately happens on the previous evening, the invariant "prepared and claimed on the session's own ET day" (in `save_run`, `claim`, and now `record_due`) must be revisited together, not one at a time.
- The `reasons` map in `worker.py` and `allowed_reasons` in `runtime.py` must stay in sync; a new `RunnerFailure` code needs entries in both. A reviewer should check that any new reason string is lowercase snake_case and surfaces in the private dashboard's attempt view (`app/dashboard/queries.py`, runtime section).
- Deferred: the public activity projection may render attempt reasons; if it maps reasons to labels, `subprocess_pipe_cleanup_failed` needs a label there (checked in Step 4.4).
