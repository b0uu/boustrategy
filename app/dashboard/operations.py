"""Host and runtime operations for the private dashboard.

Reads Task Scheduler, the bot's Codex home, runtime tables and local logs. Every
mutation reuses the trusted operation the CLI performs; nothing here starts a
model in-process or touches a broker.
"""

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.dashboard.queries import selected_rows, table_exists
from app.storage.runtime import expire, finish, get_attempt, get_run, immediate
from app.storage.schedules import latest_schedule, planned_preview, save_schedule

TASK_NAME = re.compile(r"^boustrategy-[a-z0-9-]{1,80}$")
TASK_COMMANDS = {
    "enable": "Enable-ScheduledTask",
    "disable": "Disable-ScheduledTask",
    "run": "Start-ScheduledTask",
}
SCHEDULE_ACTIONS = {"pause", "resume", "reconcile"}
RETRYABLE = {"failed", "blocked", "timed_out", "canceled", "expired"}
_UNSET_TASK_TIME = "1999-"

_LIST_TASKS = (
    "Get-ScheduledTask -TaskName 'boustrategy-*' | ForEach-Object { "
    "$i = $_ | Get-ScheduledTaskInfo; [pscustomobject]@{ name=$_.TaskName; state=[string]$_.State; "
    "last_run=$i.LastRunTime.ToString('o'); last_result=$i.LastTaskResult; "
    "next_run=$i.NextRunTime.ToString('o'); logon=[string]$_.Principal.LogonType } } "
    "| ConvertTo-Json -Compress"
)

HostRunner = Callable[[str], str]
Spawner = Callable[[list[str], Path, dict[str, str]], None]


def powershell(script: str) -> str:
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return completed.stdout


def host_tasks(run: HostRunner = powershell) -> list[dict[str, Any]] | None:
    try:
        raw = run(_LIST_TASKS).strip()
        parsed = json.loads(raw) if raw else []
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    items = parsed if isinstance(parsed, list) else [parsed]
    tasks = []
    for item in items:
        if not isinstance(item, dict) or not TASK_NAME.fullmatch(str(item.get("name", ""))):
            continue
        last_run = str(item.get("last_run", ""))
        next_run = str(item.get("next_run", ""))
        tasks.append(
            {
                "name": item["name"],
                "state": str(item.get("state", "")),
                "last_run": None if last_run.startswith(_UNSET_TASK_TIME) else last_run,
                "last_result": item.get("last_result"),
                "next_run": None if next_run.startswith(_UNSET_TASK_TIME) else next_run,
                "logon": str(item.get("logon", "")),
            }
        )
    return sorted(tasks, key=lambda task: task["name"])


def task_action(name: str, action: str, run: HostRunner = powershell) -> None:
    if not TASK_NAME.fullmatch(name):
        raise ValueError("unknown task name")
    if action not in TASK_COMMANDS:
        raise ValueError("unknown task action")
    run(f"{TASK_COMMANDS[action]} -TaskName '{name}' -ErrorAction Stop | Out-Null")


def local_config(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = re.fullmatch(r"\s*(\w+)\s*=\s*['\"](.*)['\"]\s*", line)
        if match:
            values[match.group(1)] = match.group(2)
    return values


def agent_status(config: dict[str, str]) -> list[dict[str, str]]:
    codex_home = Path(config.get("CodexHome") or Path.home() / ".codex-boustrategy")
    codex_exe = config.get("CodexExe") or "codex"
    auth = codex_home / "auth.json"
    grants = list(codex_home.glob("**/mcp_oauth*")) if codex_home.is_dir() else []

    def stamp(path: Path) -> str:
        return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(timespec="seconds")

    return [
        {
            "item": "Codex CLI on PATH",
            "status": "ready" if shutil.which(codex_exe) else "missing",
            "detail": shutil.which(codex_exe) or codex_exe,
        },
        {
            "item": "Bot Codex home",
            "status": "ready" if codex_home.is_dir() else "missing",
            "detail": str(codex_home),
        },
        {
            "item": "Codex login",
            "status": "ready" if auth.is_file() else "missing",
            "detail": f"auth.json saved {stamp(auth)}" if auth.is_file() else "run codex login",
        },
        {
            "item": "Robinhood MCP grant",
            "status": "ready" if grants else "missing",
            "detail": f"saved {stamp(grants[0])}"
            if grants
            else "run codex mcp login robinhood-trading",
        },
        {
            "item": "X bearer token",
            "status": "ready" if os.environ.get("X_BEARER_TOKEN") else "missing",
            "detail": "user environment variable",
        },
        {
            "item": "Digest model",
            "status": "ready" if config.get("DigestModel") else "missing",
            "detail": (
                f"{config.get('DigestModel', '')} · effort "
                f"{config.get('DigestReasoningEffort', 'default')}"
            ),
        },
        {
            "item": "Review model",
            "status": "ready" if config.get("ReviewModel") else "missing",
            "detail": config.get("ReviewModel", ""),
        },
        {
            "item": "Discord webhook",
            "status": "ready" if config.get("DiscordWebhookUrl") else "pending",
            "detail": "configured" if config.get("DiscordWebhookUrl") else "notifications off",
        },
    ]


def schedule_status(conn: sqlite3.Connection, schedule_id: str, now: datetime) -> dict[str, Any]:
    schedule = (
        latest_schedule(conn, schedule_id) if table_exists(conn, "schedule_revisions") else None
    )
    occurrences = (
        selected_rows(
            conn,
            "SELECT occurrence_id, session_date, due_at, status, reason, observed_at "
            "FROM schedule_occurrences WHERE schedule_id=? ORDER BY due_at DESC LIMIT 10",
            (schedule_id,),
        )
        if table_exists(conn, "schedule_occurrences")
        else None
    )
    attempts = (
        selected_rows(
            conn,
            "SELECT a.attempt_id, a.run_id, r.session_date, r.slot, r.mode, a.status, a.stage, "
            "a.model, a.observed_model, a.started_at, a.heartbeat_at, a.finished_at, a.reason "
            "FROM runtime_attempts a JOIN runtime_runs r ON r.run_id=a.run_id "
            "ORDER BY a.started_at DESC LIMIT 15",
        )
        if table_exists(conn, "runtime_attempts") and table_exists(conn, "runtime_runs")
        else None
    )
    leases = (
        selected_rows(
            conn,
            "SELECT scope_key, attempt_id, expires_at FROM runtime_leases "
            "WHERE attempt_id IS NOT NULL",
        )
        if table_exists(conn, "runtime_leases")
        else []
    )
    return {
        "schedule_id": schedule_id,
        "schedule": schedule.model_dump(mode="json") if schedule else None,
        "preview": planned_preview(schedule, now, limit=5)["items"] if schedule else [],
        "occurrences": occurrences,
        "attempts": attempts,
        "leases": leases,
    }


def schedule_action(
    conn: sqlite3.Connection, schedule_id: str, action: str, now: datetime
) -> dict[str, Any]:
    if action not in SCHEDULE_ACTIONS:
        raise ValueError("unknown schedule action")
    if action == "reconcile":
        with immediate(conn):
            return {"expired_attempts": expire(conn, now)}
    previous = latest_schedule(conn, schedule_id)
    if previous is None:
        raise ValueError("schedule not found")
    if previous.mode == "live":
        raise ValueError("live schedule controls stay on the CLI with the account profile")
    schedule = previous.model_copy(
        update={
            "revision": previous.revision + 1,
            "configured_at": now,
            "paused": action == "pause",
        }
    )
    save_schedule(conn, schedule, None)
    return {"revision": schedule.revision, "paused": schedule.paused}


def spawn_detached(argv: list[str], log_path: Path, env: dict[str, str]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab") as log:
        subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
            close_fds=True,
            creationflags=(
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
                if os.name == "nt"
                else 0
            ),
            start_new_session=os.name != "nt",
        )


def cancel_attempt(conn: sqlite3.Connection, attempt_id: str, now: datetime) -> dict[str, Any]:
    attempt = get_attempt(conn, attempt_id)
    if attempt.status != "running":
        raise ValueError("only a running attempt can be canceled")
    finished = finish(
        conn, attempt.attempt_id, attempt.fence, now, status="canceled", reason="operator_canceled"
    )
    return {"attempt_id": finished.attempt_id, "status": finished.status}


def retry_attempt(
    conn: sqlite3.Connection,
    attempt_id: str,
    *,
    db_path: Path,
    model: str,
    logs_dir: Path,
    codex_home: str,
    spawn: Spawner = spawn_detached,
) -> dict[str, Any]:
    attempt = get_attempt(conn, attempt_id)
    latest = conn.execute(
        "SELECT attempt_id, status FROM runtime_attempts WHERE run_id=? "
        "ORDER BY attempt_number DESC LIMIT 1",
        (attempt.run_id,),
    ).fetchone()
    if latest[0] != attempt.attempt_id:
        raise ValueError("a newer attempt exists for this run; refresh and review it")
    if attempt.status not in RETRYABLE:
        raise ValueError(f"attempt status {attempt.status} isn't retryable")
    if not model.strip():
        raise ValueError("retry requires a configured review model")
    run = get_run(conn, attempt.run_id)
    log_path = logs_dir / f"retry-{run.run_id}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.log"
    env = dict(os.environ)
    if codex_home:
        env["CODEX_HOME"] = codex_home
    spawn(
        [
            sys.executable,
            "-m",
            "app.reason.runtime",
            "--db",
            str(db_path),
            "retry",
            "--run",
            run.run_id,
            "--model",
            model,
            "--logs",
            str(logs_dir.parent / "runtime-logs"),
        ],
        log_path,
        env,
    )
    return {"run_id": run.run_id, "log": log_path.name}


def log_tails(logs_dir: Path, *, files_per_kind: int = 3, lines: int = 25) -> list[dict[str, Any]]:
    tails = []
    for kind in ("digester", "runtime"):
        folder = logs_dir / kind
        if not folder.is_dir():
            continue
        files = sorted(
            (item for item in folder.glob("*.log") if item.is_file()),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )[:files_per_kind]
        for item in files:
            text = item.read_text(encoding="utf-8", errors="replace").splitlines()
            tails.append(
                {
                    "kind": kind,
                    "name": item.name,
                    "modified": datetime.fromtimestamp(item.stat().st_mtime, UTC).isoformat(
                        timespec="seconds"
                    ),
                    "tail": "\n".join(text[-lines:]),
                }
            )
    return tails
