import subprocess
import sys
from pathlib import Path
from time import perf_counter

import pytest

from app.reason.codex_runner import RunnerFailure, run_codex, strict_output_schema, validate_output


def test_strict_schema_has_required_closed_objects_and_nullable_optional_fields() -> None:
    schema = strict_output_schema()
    pending = [schema]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)
    assert (
        validate_output(
            '{"decisions":null,"thesis_reviews":null,"public_summary":"No action."}'
        ).decisions
        == []
    )


@pytest.mark.parametrize("child", [False, True])
def test_real_local_fake_process_exits_and_releases_inherited_pipes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, child: bool
) -> None:
    script = tmp_path / "fake.py"
    script.write_text(
        "import sys,json,subprocess\n"
        "prompt=sys.stdin.read()\n"
        + (
            "subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\n"
            if child
            else ""
        )
        + "print(json.dumps({'type':'item.completed','item':{'type':'agent_message',"
        "'text':json.dumps({'decisions':[],'thesis_reviews':[],"
        "'public_summary':'No action.'})}}),flush=True)\n",
        encoding="utf-8",
    )
    real_popen = subprocess.Popen
    captured = {}

    def fake(argv: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
        captured.update(kwargs)
        captured["argv"] = argv
        return real_popen([sys.executable, str(script)], **kwargs)  # type: ignore[call-overload,no-any-return]

    monkeypatch.setattr("app.reason.codex_runner.subprocess.Popen", fake)
    monkeypatch.setenv("X_BEARER_TOKEN", "PRIVATE_X_TOKEN")
    monkeypatch.setenv("BROKER_API_KEY", "PRIVATE_BROKER_TOKEN")
    started = perf_counter()
    result = run_codex(
        "Deliberate intake", model="explicit-model", log_dir=tmp_path / "logs", timeout_seconds=5
    )
    assert result.public_summary == "No action."
    assert perf_counter() - started < 10
    assert captured["cwd"] != Path.cwd()
    assert "X_BEARER_TOKEN" not in captured["env"] and "BROKER_API_KEY" not in captured["env"]  # type: ignore[operator]
    assert "--ignore-user-config" in captured["argv"]  # type: ignore[operator]
    assert "--sandbox" in captured["argv"]  # type: ignore[operator]


def test_runner_timeout_and_cancel_stop_real_local_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "fake.py"
    script.write_text("import time; time.sleep(60)", encoding="utf-8")
    real_popen = subprocess.Popen

    def fake(argv: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
        return real_popen([sys.executable, str(script)], **kwargs)  # type: ignore[call-overload,no-any-return]

    monkeypatch.setattr("app.reason.codex_runner.subprocess.Popen", fake)
    with pytest.raises(RunnerFailure, match="runner_timeout"):
        run_codex("intake", model="model", log_dir=tmp_path / "timeout", timeout_seconds=0.1)
    with pytest.raises(RunnerFailure, match="runner_canceled"):
        run_codex("intake", model="model", log_dir=tmp_path / "cancel", cancelled=lambda: True)


def test_cleanup_failure_does_not_mask_runner_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "fake.py"
    script.write_text("import time; time.sleep(60)", encoding="utf-8")
    real_popen = subprocess.Popen

    def fake(argv: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
        process: subprocess.Popen[bytes] = real_popen(  # type: ignore[call-overload]
            [sys.executable, str(script)], **kwargs
        )
        original_wait = process.wait

        def failing_wait(timeout: float | None = None) -> int:
            original_wait(timeout=timeout)
            raise subprocess.TimeoutExpired(argv, timeout or 0)

        process.wait = failing_wait  # type: ignore[method-assign]
        return process

    monkeypatch.setattr("app.reason.codex_runner.subprocess.Popen", fake)
    with pytest.raises(RunnerFailure, match="runner_timeout"):
        run_codex("intake", model="model", log_dir=tmp_path / "logs", timeout_seconds=0.2)


@pytest.mark.parametrize(
    "event", ["{broken", "[]", "null", "42", '{"type":"item.completed","item":[]}']
)
def test_runner_rejects_malformed_protocol_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    event: str,
) -> None:
    script = tmp_path / "fake.py"
    script.write_text("print(" + repr(event) + ", flush=True)", encoding="utf-8")
    real_popen = subprocess.Popen

    def fake(argv: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
        return real_popen([sys.executable, str(script)], **kwargs)  # type: ignore[call-overload,no-any-return]

    monkeypatch.setattr("app.reason.codex_runner.subprocess.Popen", fake)
    with pytest.raises(RunnerFailure, match="invalid_output"):
        run_codex("intake", model="model", log_dir=tmp_path / "logs")
