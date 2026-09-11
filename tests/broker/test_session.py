import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from app.broker.session import BrokerSessionFailure, run_broker_session, strict_json_schema


class Reply(BaseModel):
    answer: str
    count: int = 0


def _fake_run(payload: str | None, returncode: int = 0, *, seen: dict[str, Any]) -> Any:
    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        if payload is not None:
            Path(argv[argv.index("--output-last-message") + 1]).write_text(
                payload, encoding="utf-8"
            )
        return subprocess.CompletedProcess(argv, returncode, b"stdout", b"stderr")

    return run


def test_session_returns_validated_output_and_isolates_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("X_BEARER_TOKEN", "secret")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    seen: dict[str, Any] = {}
    log = tmp_path / "session.log"

    reply = run_broker_session(
        "hello",
        schema=Reply,
        model="gpt-5.6-luna",
        codex_home=tmp_path / "home",
        run=_fake_run(json.dumps({"answer": "ok", "count": 2}), seen=seen),
        log_path=log,
    )

    argv = seen["argv"]
    env = seen["kwargs"]["env"]
    assert reply == Reply(answer="ok", count=2)
    assert argv[1:3] == ["exec", "--sandbox"] and argv[3] == "read-only"
    assert "mcp_servers.robinhood-trading.enabled=true" in argv
    assert "--ignore-user-config" not in argv
    assert env["CODEX_HOME"] == str(tmp_path / "home")
    assert "X_BEARER_TOKEN" not in env and "OPENAI_API_KEY" not in env
    assert seen["kwargs"]["input"] == b"hello"
    assert "stdout" in log.read_text(encoding="utf-8") and "exit 0" in log.read_text()
    schema = (
        json.loads(Path(argv[argv.index("--output-schema") + 1]).read_text())
        if Path(argv[argv.index("--output-schema") + 1]).exists()
        else strict_json_schema(Reply)
    )
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"answer", "count"}
    # A session that names no tools gets no approval overrides: order tools stay gated.
    assert not any("approval_mode" in part for part in argv)
    assert argv[-1] == "-"


def test_only_named_tools_are_approved_and_names_are_validated(tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    run_broker_session(
        "execute",
        schema=Reply,
        model="gpt-5.6-sol",
        codex_home=tmp_path / "home",
        run=_fake_run(json.dumps({"answer": "ok"}), seen=seen),
        approved_tools=("review_equity_order", "place_equity_order"),
    )

    argv = seen["argv"]
    overrides = [argv[i + 1] for i, part in enumerate(argv) if part == "-c"]
    assert (
        "mcp_servers.robinhood-trading.tools.review_equity_order.approval_mode=approve" in overrides
    )
    assert (
        "mcp_servers.robinhood-trading.tools.place_equity_order.approval_mode=approve" in overrides
    )
    assert sum("approval_mode" in item for item in overrides) == 2
    assert argv[-1] == "-"
    with pytest.raises(ValueError, match="tool name"):
        run_broker_session(
            "x",
            schema=Reply,
            model="m",
            codex_home=tmp_path,
            run=_fake_run("{}", seen={}),
            approved_tools=("place_equity_order.approval_mode=approve -c x",),
        )


def test_executor_approves_exactly_review_and_place() -> None:
    from app.broker.executor import EXECUTION_TOOLS

    assert EXECUTION_TOOLS == ("review_equity_order", "place_equity_order")


def test_session_failures_are_named(tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    with pytest.raises(BrokerSessionFailure, match="session_exit_3"):
        run_broker_session(
            "x",
            schema=Reply,
            model="m",
            codex_home=tmp_path,
            run=_fake_run('{"answer":"a"}', 3, seen=seen),
        )
    with pytest.raises(BrokerSessionFailure, match="session_no_output"):
        run_broker_session(
            "x", schema=Reply, model="m", codex_home=tmp_path, run=_fake_run(None, seen=seen)
        )
    with pytest.raises(BrokerSessionFailure, match="session_invalid_output"):
        run_broker_session(
            "x",
            schema=Reply,
            model="m",
            codex_home=tmp_path,
            run=_fake_run('{"count":"x"}', seen=seen),
        )
    with pytest.raises(BrokerSessionFailure, match="prompt_too_large"):
        run_broker_session(
            "x" * 300_000,
            schema=Reply,
            model="m",
            codex_home=tmp_path,
            run=_fake_run(None, seen=seen),
        )

    def timing_out(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(argv, 1, output=b"partial", stderr=b"")

    with pytest.raises(BrokerSessionFailure, match="session_timeout"):
        run_broker_session("x", schema=Reply, model="m", codex_home=tmp_path, run=timing_out)
    with pytest.raises(ValueError, match="sandbox"):
        run_broker_session(
            "x", schema=Reply, model="m", codex_home=tmp_path, sandbox="danger-full-access"
        )
