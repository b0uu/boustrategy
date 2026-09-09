"""Bounded noninteractive authoring. This adapter never submits orders."""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

from app.reason.process_tree import WindowsProcessTree
from app.schemas.runtime import AuthoredOutput

MAX_PROMPT_BYTES = 512_000
MAX_STREAM_BYTES = 8_000_000
MAX_RESULT_BYTES = 1_000_000


class RunnerFailure(ValueError):
    pass


def strict_output_schema() -> dict[str, Any]:
    schema = AuthoredOutput.model_json_schema()

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
    schema["$defs"]["InvestmentDecisionRecord"]["properties"]["created_at"] = {
        "anyOf": [{"type": "string", "format": "date-time"}, {"type": "null"}]
    }
    return schema


def validate_output(raw: str) -> AuthoredOutput:
    if len(raw.encode()) > MAX_RESULT_BYTES:
        raise RunnerFailure("output_too_large")
    schema = AuthoredOutput.model_json_schema()

    def defaults(value: Any, node: dict[str, Any]) -> Any:
        if "$ref" in node:
            node = schema["$defs"][node["$ref"].split("/")[-1]]
        if "anyOf" in node and value is not None:
            node = next(part for part in node["anyOf"] if part.get("type") != "null")
            return defaults(value, node)
        if isinstance(value, list):
            return [defaults(item, node.get("items", {})) for item in value]
        if isinstance(value, dict):
            properties, required = node.get("properties", {}), node.get("required", [])
            return {
                name: defaults(item, properties.get(name, {}))
                for name, item in value.items()
                if not (
                    item is None
                    and name not in required
                    and name in properties
                    and not any(
                        part.get("type") == "null" for part in properties[name].get("anyOf", [])
                    )
                )
            }
        return value

    parsed = defaults(json.loads(raw), schema)
    if isinstance(parsed, dict) and isinstance(parsed.get("decisions", []), list):
        for decision in parsed.get("decisions", []):
            if isinstance(decision, dict):
                decision["created_at"] = datetime.now(UTC).isoformat()
    return AuthoredOutput.model_validate(parsed)


def run_codex(
    prompt: str,
    *,
    model: str,
    log_dir: Path,
    executable: str = "codex",
    timeout_seconds: float = 1800,
    pulse: Callable[[], None] = lambda: None,
    cancelled: Callable[[], bool] = lambda: False,
) -> AuthoredOutput:
    encoded = prompt.encode("utf-8")
    if len(encoded) > MAX_PROMPT_BYTES:
        raise RunnerFailure("intake_too_large")
    if not model.strip() or timeout_seconds <= 0:
        raise ValueError("runner requires explicit model and positive timeout")
    log_dir.mkdir(parents=True, exist_ok=True)
    exceeded = threading.Event()
    reader_errors: list[OSError] = []
    with tempfile.TemporaryDirectory(prefix="bou-authoring-") as folder:
        work = Path(folder)
        schema_path = work / "output-schema.json"
        schema_path.write_text(json.dumps(strict_output_schema()), encoding="utf-8")
        # npm installs Codex on Windows as a .cmd shim, which CreateProcess won't
        # find from a bare name; resolve through PATHEXT and fall back unchanged.
        argv = [
            shutil.which(executable) or executable,
            "exec",
            "--json",
            "--output-schema",
            str(schema_path),
            "--sandbox",
            "read-only",
            "--ignore-user-config",
            "--ephemeral",
            "--skip-git-repo-check",
            "--model",
            model,
            "--color",
            "never",
            "-",
        ]
        prompt_path = work / "prompt.txt"
        prompt_path.write_bytes(encoded)
        prompt_stream = prompt_path.open("rb")
        allowed_environment = {
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
            "CODEX_HOME",
            "OPENAI_API_KEY",
            "LANG",
            "LC_ALL",
        }
        environment = {
            key: value for key, value in os.environ.items() if key.upper() in allowed_environment
        }
        try:
            process = subprocess.Popen(
                argv,
                cwd=work,
                env=environment,
                stdin=prompt_stream,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.CREATE_NO_WINDOW
                | 0x00000004
                if os.name == "nt"
                else 0,
                start_new_session=os.name != "nt",
            )
        except OSError:
            prompt_stream.close()
            raise
        assert process.stdout and process.stderr

        def drain(stream: BinaryIO, path: Path) -> None:
            try:
                with path.open("wb") as output:
                    size = 0
                    while chunk := stream.read(4096):
                        remaining = MAX_STREAM_BYTES - size
                        output.write(chunk[:remaining])
                        size += len(chunk)
                        if size > MAX_STREAM_BYTES:
                            exceeded.set()
                            break
            except OSError as error:
                reader_errors.append(error)
                exceeded.set()
            finally:
                stream.close()

        readers = [
            threading.Thread(target=drain, args=(process.stdout, log_dir / "events.jsonl")),
            threading.Thread(target=drain, args=(process.stderr, log_dir / "stderr.log")),
        ]
        for reader in readers:
            reader.start()
        tree = None
        started = time.monotonic()
        last_pulse = started - 10
        cleanup_failure: RunnerFailure | None = None
        try:
            if sys.platform == "win32":
                tree = WindowsProcessTree(process.pid)
                tree.resume(process.pid)
            while process.poll() is None:
                current = time.monotonic()
                if exceeded.is_set():
                    raise RunnerFailure("output_too_large")
                if cancelled():
                    raise RunnerFailure("runner_canceled")
                if current - started >= timeout_seconds:
                    raise RunnerFailure("runner_timeout")
                if current - last_pulse >= 10:
                    pulse()
                    last_pulse = current
                time.sleep(0.05)
            if process.returncode != 0:
                raise RunnerFailure("runner_failed")
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
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                cleanup_failure = RunnerFailure("subprocess_pipe_cleanup_failed")
            for reader in readers:
                reader.join(timeout=10)
                if reader.is_alive():
                    cleanup_failure = RunnerFailure("subprocess_pipe_cleanup_failed")
            prompt_stream.close()
        if cleanup_failure is not None:
            raise cleanup_failure
        if reader_errors:
            raise RunnerFailure("log_write_failed") from reader_errors[0]
        if exceeded.is_set():
            raise RunnerFailure("output_too_large")
        result = None
        with (log_dir / "events.jsonl").open(encoding="utf-8") as events:
            for line in events:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as error:
                    raise RunnerFailure("invalid_output") from error
                if not isinstance(event, dict):
                    raise RunnerFailure("invalid_output")
                item = event.get("item", {})
                if not isinstance(item, dict):
                    raise RunnerFailure("invalid_output")
                if event.get("type") == "item.completed" and item.get("type") == "agent_message":
                    result = item.get("text")
        if not isinstance(result, str):
            raise RunnerFailure("invalid_output")
        return validate_output(result)
