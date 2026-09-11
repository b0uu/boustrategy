"""Bounded, schema-checked Codex sessions that may call the Robinhood MCP server.

The authoring runner deliberately ignores user configuration so it can never reach
a broker. Broker sessions are the opposite: they load the bot's Codex home, where
the Robinhood grant lives, and return one structured object that trusted code
validates before anything is persisted.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

MAX_PROMPT_BYTES = 200_000
MAX_OUTPUT_BYTES = 200_000
MAX_LOG_BYTES = 2_000_000
_TOOL_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")
_ALLOWED_ENVIRONMENT = {
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "PATH",
    "PATHEXT",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "HOME",
    "APPDATA",
    "LOCALAPPDATA",
    "LANG",
    "LC_ALL",
}

Runner = Callable[..., subprocess.CompletedProcess[bytes]]


class BrokerSessionFailure(ValueError):
    pass


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema()

    def strict(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                properties = node.get("properties", {})
                required = set(node.get("required", []))
                node["additionalProperties"] = False
                node["required"] = list(properties)
                for name, prop in properties.items():
                    prop.pop("default", None)
                    if name not in required and not any(
                        item.get("type") == "null" for item in prop.get("anyOf", [])
                    ):
                        properties[name] = {"anyOf": [prop, {"type": "null"}]}
            for child in node.values():
                strict(child)
        elif isinstance(node, list):
            for child in node:
                strict(child)

    strict(schema)
    return schema


def run_broker_session[T: BaseModel](
    prompt: str,
    *,
    schema: type[T],
    model: str,
    codex_home: str | Path,
    timeout_seconds: float = 300.0,
    sandbox: str = "read-only",
    cwd: str | Path | None = None,
    executable: str = "codex",
    log_path: Path | None = None,
    run: Runner = subprocess.run,
    approved_tools: tuple[str, ...] = (),
) -> T:
    encoded = prompt.encode("utf-8")
    if not encoded.strip() or len(encoded) > MAX_PROMPT_BYTES:
        raise BrokerSessionFailure("prompt_too_large")
    if not model.strip() or not str(codex_home).strip() or timeout_seconds <= 0:
        raise ValueError("broker session requires a model, a Codex home and a positive timeout")
    if sandbox not in {"read-only", "workspace-write"}:
        raise ValueError("broker session sandbox must be read-only or workspace-write")
    with tempfile.TemporaryDirectory(prefix="bou-broker-") as folder:
        work = Path(folder)
        schema_path = work / "schema.json"
        last_message = work / "last-message.json"
        schema_path.write_text(json.dumps(strict_json_schema(schema)), encoding="utf-8")
        argv = [
            shutil.which(executable) or executable,
            "exec",
            "--sandbox",
            sandbox,
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(last_message),
            "--color",
            "never",
            "--skip-git-repo-check",
            "--ephemeral",
            "-C",
            str(cwd or work),
            "-m",
            model,
            "-c",
            "mcp_servers.robinhood-trading.enabled=true",
        ]
        # The broker marks order tools as needing approval, and an unattended session's
        # approval policy is never, so Codex rejects them outright. Only the execution
        # session names the tools it may call without a human; every other session keeps
        # the broker's default and cannot place or review an order.
        for tool in approved_tools:
            if not _TOOL_NAME.fullmatch(tool):
                raise ValueError("invalid broker tool name")
            argv += ["-c", f"mcp_servers.robinhood-trading.tools.{tool}.approval_mode=approve"]
        argv.append("-")
        environment = {
            key: value for key, value in os.environ.items() if key.upper() in _ALLOWED_ENVIRONMENT
        }
        environment["CODEX_HOME"] = str(codex_home)
        try:
            completed = run(
                argv,
                input=encoded,
                capture_output=True,
                timeout=timeout_seconds,
                env=environment,
                cwd=str(cwd or work),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except subprocess.TimeoutExpired as error:
            _write_log(log_path, error.stdout, error.stderr, "session_timeout")
            raise BrokerSessionFailure("session_timeout") from error
        except OSError as error:
            raise BrokerSessionFailure("session_launch_failed") from error
        _write_log(log_path, completed.stdout, completed.stderr, f"exit {completed.returncode}")
        if completed.returncode != 0:
            raise BrokerSessionFailure(f"session_exit_{completed.returncode}")
        if not last_message.is_file():
            raise BrokerSessionFailure("session_no_output")
        raw = last_message.read_bytes()
        if len(raw) > MAX_OUTPUT_BYTES:
            raise BrokerSessionFailure("session_output_too_large")
        try:
            return schema.model_validate_json(raw)
        except ValidationError as error:
            raise BrokerSessionFailure("session_invalid_output") from error


def _write_log(
    log_path: Path | None, stdout: bytes | None, stderr: bytes | None, footer: str
) -> None:
    if log_path is None:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    body = (
        (stdout or b"")[-MAX_LOG_BYTES:] + b"\n--- stderr ---\n" + (stderr or b"")[-MAX_LOG_BYTES:]
    )
    log_path.write_bytes(body + f"\n--- {footer} ---\n".encode())
