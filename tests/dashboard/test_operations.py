import hashlib
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.dashboard import operations
from app.dashboard.server import create_app
from app.schemas.runtime import RuntimeRun, ScheduleRevision
from app.storage.database import connect
from app.storage.runtime import claim, get_attempt
from app.storage.schedules import latest_schedule, save_schedule
from app.x.calendar import NEW_YORK

TASKS_JSON = json.dumps(
    [
        {
            "name": "boustrategy-digester-morning",
            "state": "Disabled",
            "last_run": "2026-08-26T08:45:45.0000000-04:00",
            "last_result": 1,
            "next_run": "2026-09-09T08:45:45.0000000-04:00",
            "logon": "Interactive",
        },
        {
            "name": "boustrategy-review-poller",
            "state": "Ready",
            "last_run": "1999-11-30T00:00:00.0000000-05:00",
            "last_result": 267011,
            "next_run": "2026-09-09T15:15:15.0000000-04:00",
            "logon": "Password",
        },
        {"name": "<script>", "state": "Ready"},
    ]
)


def _client(
    tmp_path: Path, runner: operations.HostRunner, spawner: operations.Spawner | None = None
) -> TestClient:
    calls: list[list[str]] = []

    def spawn(argv: list[str], log_path: Path, env: dict[str, str]) -> None:
        calls.append(argv)

    client = TestClient(
        create_app(
            tmp_path / "boustrategy.db",
            local_config_path=tmp_path / "digester.local.psd1",
            host_runner=runner,
            spawner=spawner or spawn,
        )
    )
    client.spawned = calls
    return client


def _token(client: TestClient) -> str:
    text = client.get("/operations").text
    return str(text.split("name='csrf_token' value='")[1].split("'")[0])


def _paper_run(tmp_path: Path, run_id: str = "runtime_test") -> RuntimeRun:
    intake = tmp_path / "intake.md"
    intake.write_text("# intake\n", encoding="utf-8")
    now = datetime.now(UTC)
    return RuntimeRun(
        run_id=run_id,
        mode="paper",
        account_id="paper",
        session_date=now.astimezone(NEW_YORK).date(),
        slot="close",
        prepared_at=now - timedelta(minutes=1),
        intake_path=str(intake),
        intake_sha256=hashlib.sha256(intake.read_bytes()).hexdigest(),
    )


def test_operations_page_renders_when_host_and_runtime_are_unavailable(tmp_path: Path) -> None:
    def failing(script: str) -> str:
        raise OSError("powershell missing")

    client = _client(tmp_path, failing)

    response = client.get("/operations")

    assert response.status_code == 200
    assert "Task Scheduler couldn't be read" in response.text
    assert "configure a schedule revision" in response.text
    assert "Codex login" in response.text
    assert "none yet" in response.text


def test_operations_page_lists_host_tasks_and_filters_unknown_names(tmp_path: Path) -> None:
    client = _client(tmp_path, lambda script: TASKS_JSON)

    text = client.get("/operations").text

    assert "boustrategy-digester-morning" in text
    assert "boustrategy-review-poller" in text
    assert "<td class='mono'>&lt;script&gt;" not in text and "<td class='mono'><script>" not in text
    assert "data-status='Disabled'" in text
    assert "data-status='Ready'" in text
    assert "value='enable'" in text
    assert "value='disable'" in text
    assert "1999-11-30" not in text


def test_task_action_requires_token_validates_name_and_calls_host(tmp_path: Path) -> None:
    scripts: list[str] = []

    def runner(script: str) -> str:
        scripts.append(script)
        return TASKS_JSON

    client = _client(tmp_path, runner)
    token = _token(client)

    forbidden = client.post(
        "/operations/task", data={"name": "boustrategy-review-poller", "action": "enable"}
    )
    invalid = client.post(
        "/operations/task",
        data={"csrf_token": token, "name": "Other-Task", "action": "enable"},
    )
    accepted = client.post(
        "/operations/task",
        data={"csrf_token": token, "name": "boustrategy-review-poller", "action": "enable"},
        follow_redirects=False,
    )

    assert forbidden.status_code == 403
    assert invalid.status_code == 400
    assert accepted.status_code == 303
    assert "Enable-ScheduledTask -TaskName 'boustrategy-review-poller'" in scripts[-1]
    assert "enable accepted" in client.get(accepted.headers["location"]).text


def test_task_action_reports_host_refusal_without_redirect(tmp_path: Path) -> None:
    def runner(script: str) -> str:
        if "Start-ScheduledTask" in script:
            raise subprocess.CalledProcessError(1, "powershell", stderr="access denied")
        return TASKS_JSON

    client = _client(tmp_path, runner)

    response = client.post(
        "/operations/task",
        data={"csrf_token": _token(client), "name": "boustrategy-review-poller", "action": "run"},
    )

    assert response.status_code == 502
    assert "Task Scheduler refused run" in response.text


def test_schedule_pause_and_resume_record_new_revisions(tmp_path: Path) -> None:
    client = _client(tmp_path, lambda script: "[]")
    db_path = tmp_path / "boustrategy.db"
    conn = connect(db_path, wal=True)
    save_schedule(
        conn,
        ScheduleRevision(
            schedule_id="paper-close",
            revision=1,
            mode="paper",
            account_id="paper",
            configured_at=datetime.now(UTC) - timedelta(minutes=5),
            enabled=True,
            schedule_mode="scheduled",
        ),
        None,
    )
    conn.close()
    token = _token(client)

    paused = client.post(
        "/operations/schedule",
        data={"csrf_token": token, "schedule_id": "paper-close", "action": "pause"},
        follow_redirects=False,
    )
    after_pause = latest_schedule(connect(db_path), "paper-close")
    page_paused = client.get("/operations").text
    resumed = client.post(
        "/operations/schedule",
        data={"csrf_token": token, "schedule_id": "paper-close", "action": "resume"},
        follow_redirects=False,
    )
    after_resume = latest_schedule(connect(db_path), "paper-close")
    unknown = client.post(
        "/operations/schedule",
        data={"csrf_token": token, "schedule_id": "missing", "action": "pause"},
    )

    assert paused.status_code == 303 and resumed.status_code == 303
    assert after_pause is not None and after_pause.revision == 2 and after_pause.paused
    assert "data-status='paused'" in page_paused and "Resume claims" in page_paused
    assert after_resume is not None and after_resume.revision == 3 and not after_resume.paused
    assert unknown.status_code == 400
    assert "schedule not found" in unknown.text


def test_attempt_cancel_then_retry_spawns_detached_cli(tmp_path: Path) -> None:
    client = _client(tmp_path, lambda script: "[]")
    (tmp_path / "digester.local.psd1").write_text(
        '@{\n    ReviewModel = "gpt-5.6-sol"\n    CodexHome = "C:\\\\bot-home"\n}\n',
        encoding="utf-8",
    )
    db_path = tmp_path / "boustrategy.db"
    conn = connect(db_path, wal=True)
    run = _paper_run(tmp_path)
    from app.storage.runtime import save_run

    save_run(conn, run)
    attempt = claim(conn, run.run_id, "gpt-5.6-sol", datetime.now(UTC))
    conn.close()
    token = _token(client)
    page_running = client.get("/operations").text

    canceled = client.post(
        "/operations/attempt",
        data={"csrf_token": token, "attempt_id": attempt.attempt_id, "action": "cancel"},
        follow_redirects=False,
    )
    stored = get_attempt(connect(db_path), attempt.attempt_id)
    retried = client.post(
        "/operations/attempt",
        data={"csrf_token": token, "attempt_id": attempt.attempt_id, "action": "retry"},
        follow_redirects=False,
    )
    second_cancel = client.post(
        "/operations/attempt",
        data={"csrf_token": token, "attempt_id": attempt.attempt_id, "action": "cancel"},
    )

    assert "value='cancel'" in page_running
    assert canceled.status_code == 303
    assert stored.status == "canceled" and stored.reason == "operator_canceled"
    assert retried.status_code == 303
    argv = client.spawned[-1]
    assert argv[1:3] == ["-m", "app.reason.runtime"]
    assert "retry" in argv and argv[argv.index("--run") + 1] == run.run_id
    assert argv[argv.index("--model") + 1] == "gpt-5.6-sol"
    assert second_cancel.status_code == 400


def test_retry_refuses_when_review_model_is_missing(tmp_path: Path) -> None:
    client = _client(tmp_path, lambda script: "[]")
    db_path = tmp_path / "boustrategy.db"
    conn = connect(db_path, wal=True)
    run = _paper_run(tmp_path)
    from app.storage.runtime import finish, save_run

    save_run(conn, run)
    attempt = claim(conn, run.run_id, "gpt-5.6-sol", datetime.now(UTC))
    finish(
        conn,
        attempt.attempt_id,
        attempt.fence,
        datetime.now(UTC),
        status="failed",
        reason="runner_failed",
    )
    conn.close()

    response = client.post(
        "/operations/attempt",
        data={"csrf_token": _token(client), "attempt_id": attempt.attempt_id, "action": "retry"},
    )

    assert response.status_code == 400
    assert "configured review model" in response.text
    assert client.spawned == []


def test_local_config_parses_psd1_and_agent_status_reads_codex_home(tmp_path: Path) -> None:
    home = tmp_path / "bot-home"
    (home / "secrets").mkdir(parents=True)
    (home / "auth.json").write_text("{}", encoding="utf-8")
    (home / "secrets" / "mcp_oauth.age").write_bytes(b"x")
    config_path = tmp_path / "digester.local.psd1"
    config_path.write_text(
        "@{\n"
        '    # comment = "ignored"\n'
        '    DiscordWebhookUrl = ""\n'
        f'    CodexHome = "{home}"\n'
        '    DigestModel = "gpt-5.6-luna"\n'
        "    DigestReasoningEffort = 'low'\n"
        "}\n",
        encoding="utf-8",
    )

    config = operations.local_config(config_path)
    status = {item["item"]: item for item in operations.agent_status(config)}

    assert config["CodexHome"] == str(home)
    assert config["DigestReasoningEffort"] == "low"
    assert config["DiscordWebhookUrl"] == ""
    assert status["Bot Codex home"]["status"] == "ready"
    assert status["Codex login"]["status"] == "ready"
    assert status["Robinhood MCP grant"]["status"] == "ready"
    assert status["Review model"]["status"] == "missing"
    assert status["Discord webhook"]["status"] == "pending"
    assert operations.local_config(tmp_path / "absent.psd1") == {}


def test_log_tails_return_newest_files_per_kind(tmp_path: Path) -> None:
    digester = tmp_path / "logs" / "digester"
    digester.mkdir(parents=True)
    for index in range(5):
        (digester / f"morning-{index}.log").write_text(
            "\n".join(f"line {n}" for n in range(40)), encoding="utf-8"
        )

    tails = operations.log_tails(tmp_path / "logs", files_per_kind=2, lines=3)

    assert len(tails) == 2
    assert all(item["kind"] == "digester" for item in tails)
    assert tails[0]["tail"] == "line 37\nline 38\nline 39"
