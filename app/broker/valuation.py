"""Market-session valuation polling: one read-only broker snapshot per scheduled tick.

The scheduled task only makes sure a worker wakes up; this module is the authority on
whether a tick may observe. It runs the existing collector ``snapshot`` command, which
fingerprint-checks the account and persists an authentic observation, and never any
preflight, review or order path. A failed or skipped tick writes nothing, so the last
good observation stays the public value. Operator alerts carry only a fixed vocabulary
of outcome codes, never collector output.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from datetime import time as clock_time
from pathlib import Path
from typing import Any

from app.x.calendar import NEW_YORK, CalendarCoverageError, session_close

REGULAR_OPEN = clock_time(9, 30)
# The broker session bounds itself at 300 s; this backstop also kills Codex children.
DEFAULT_TIMEOUT_SECONDS = 480.0
DEFAULT_ALERT_AFTER = 3
_SAFE_FAILURE = re.compile(r"^(?:[A-Za-z_][\w.]*\.)?([A-Z]\w{0,63}): ([a-z][a-z0-9_]{0,63})$")
_SUMMARY_FIELDS = ("captured_at", "account_equity", "positions")

Collector = Callable[[list[str], float], tuple[int | None, str, str]]


@dataclass(frozen=True)
class Window:
    open: bool
    reason: str
    session_date: str | None = None


def session_window(now: datetime) -> Window:
    """Decide whether ``now`` is inside an actual NYSE regular session."""
    if now.tzinfo is None:
        raise ValueError("session window requires an aware time")
    local = now.astimezone(NEW_YORK)
    day = local.date()
    try:
        close = session_close(day)
    except CalendarCoverageError:
        return Window(False, "calendar_out_of_coverage")
    if close is None:
        return Window(False, "weekend" if day.weekday() >= 5 else "holiday")
    if local < datetime.combine(day, REGULAR_OPEN, NEW_YORK):
        return Window(False, "pre_open")
    if local >= close:
        return Window(False, "after_close")
    return Window(True, "regular_session", day.isoformat())


@contextmanager
def exclusive(path: Path) -> Iterator[bool]:
    """Hold a nonblocking OS lock; yield False when another tick already holds it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = os.open(path, os.O_RDWR | os.O_CREAT)
    try:
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(handle, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            if sys.platform == "win32":
                import msvcrt

                os.lseek(handle, 0, os.SEEK_SET)
                msvcrt.locking(handle, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        os.close(handle)


def kill_tree(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(pid)],
            capture_output=True,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        import signal

        os.killpg(pid, signal.SIGKILL)


def run_collector(argv: list[str], timeout: float) -> tuple[int | None, str, str]:
    """Run the collector; on timeout kill it and every Codex process it started."""
    options: dict[str, Any] = (
        {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
        if sys.platform == "win32"
        else {"start_new_session": True}
    )
    process = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **options,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_tree(process.pid)
        stdout, stderr = process.communicate(timeout=30)
        return None, stdout, stderr
    return process.returncode, stdout, stderr


def collector_argv(db: str, profile: str, model: str, codex_home: str) -> list[str]:
    return [
        sys.executable,
        "-m",
        "app.broker.collector",
        "--db",
        db,
        "--profile",
        profile,
        "--model",
        model,
        "--codex-home",
        codex_home,
        "snapshot",
    ]


def failure_reason(returncode: int | None, stderr: str) -> str:
    """Reduce a failure to a code that cannot carry paths, identifiers or secrets."""
    if returncode is None:
        return "timeout"
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    if lines and (match := _SAFE_FAILURE.match(lines[-1])):
        return f"{match.group(1)}: {match.group(2)}"
    return f"exit_{returncode}"


def summarize(stdout: str) -> dict[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        if line.startswith("{"):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                return None
            return {key: payload.get(key) for key in _SUMMARY_FIELDS}
    return None


def load_state(path: Path) -> dict[str, Any]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"consecutive_failures": 0}
    return state if isinstance(state, dict) else {"consecutive_failures": 0}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_suffix(".tmp")
    staging.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    os.replace(staging, path)


def run(
    *,
    db: str,
    profile: str,
    model: str,
    codex_home: str,
    state_dir: Path,
    now: datetime | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    alert_after: int = DEFAULT_ALERT_AFTER,
    what_if: bool = False,
    collect: Collector = run_collector,
    monotonic: Callable[[], float] = time.monotonic,
) -> tuple[int, dict[str, Any]]:
    """Run one tick; return the exit code and a sanitized result for the operator log."""
    observed = now or datetime.now(UTC)
    window = session_window(observed)
    result: dict[str, Any] = {
        "outcome": "skipped",
        "reason": window.reason,
        "session_date": window.session_date,
        "alert": None,
    }
    if what_if:
        result["outcome"] = "what_if"
        result["would_run"] = window.open
        result["command"] = (
            f"python -m app.broker.collector --profile {profile} --model {model} "
            "--codex-home <codex-home> snapshot"
        )
        return 0, result
    if not window.open:
        return 0, result
    with exclusive(state_dir / "live-valuation.lock") as acquired:
        if not acquired:
            result.update(outcome="skipped", reason="overlap")
            return 0, result
        started = monotonic()
        returncode, stdout, stderr = collect(
            collector_argv(db, profile, model, codex_home), timeout
        )
        duration = round(monotonic() - started, 1)
        state_path = state_dir / "live-valuation.json"
        state = load_state(state_path)
        previous = int(state.get("consecutive_failures", 0))
        stamp = observed.astimezone(UTC).isoformat()
        result["duration_seconds"] = duration
        if returncode == 0:
            summary = summarize(stdout)
            result.update(outcome="success", reason="observed", summary=summary)
            state.update(consecutive_failures=0, last_success_at=stamp)
            if previous:
                result["alert"] = (
                    f"BouStrategy valuation recovered after {previous} failed "
                    f"tick{'s' if previous != 1 else ''} ({duration}s)"
                )
            save_state(state_path, state)
            result["consecutive_failures"] = 0
            return 0, result
        reason = failure_reason(returncode, stderr)
        # The local operator log keeps the tail for diagnosis; the alert never sees it.
        print(stderr[-4000:], file=sys.stderr, flush=True)
        failures = previous + 1
        state.update(consecutive_failures=failures, last_failure_at=stamp, last_reason=reason)
        save_state(state_path, state)
        result.update(outcome="failure", reason=reason, consecutive_failures=failures)
        if failures == 1:
            result["alert"] = f"BouStrategy valuation FAILED: {reason} ({duration}s)"
        elif failures % max(1, alert_after) == 0:
            result["alert"] = (
                f"BouStrategy valuation FAILED {failures} ticks in a row: {reason}. "
                "Check broker MCP authorization and the Codex identity."
            )
        return 1, result


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.broker.valuation")
    parser.add_argument("--db", default="data/boustrategy.db")
    parser.add_argument("--profile", default="codex")
    parser.add_argument("--model", required=True)
    parser.add_argument("--codex-home", required=True)
    parser.add_argument("--state-dir", default="data/state")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--alert-after", type=int, default=DEFAULT_ALERT_AFTER)
    parser.add_argument("--now", type=datetime.fromisoformat)
    parser.add_argument("--what-if", action="store_true")
    args = parser.parse_args()
    if not 30 <= args.timeout <= 600:
        parser.error("--timeout must be 30 through 600 seconds")
    code, result = run(
        db=args.db,
        profile=args.profile,
        model=args.model,
        codex_home=args.codex_home,
        state_dir=Path(args.state_dir),
        now=args.now,
        timeout=args.timeout,
        alert_after=args.alert_after,
        what_if=args.what_if,
    )
    print(json.dumps(result, sort_keys=True), flush=True)
    sys.exit(code)


if __name__ == "__main__":
    main()
