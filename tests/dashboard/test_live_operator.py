import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.broker.config import load_live_profiles, public_profile_status
from app.dashboard.queries import live_operator_status
from app.dashboard.server import create_app
from app.schemas.live_execution import LivePortfolioSnapshot
from app.schemas.reasoning_run import ReasoningRun
from app.storage.database import connect
from app.storage.records import (
    complete_reasoning_run,
    get_reasoning_run,
    save_live_portfolio_snapshot,
    save_reasoning_run,
)

NOW = datetime.now(UTC)


def _config(path: Path, *, codex_enabled: bool = True) -> Path:
    path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "execution_profile_id": "codex",
                        "agent_provider": "CODEX",
                        "account_alias": "codex-agentic",
                        "broker_account_fingerprint": "0" * 16 if codex_enabled else "",
                        "enabled": codex_enabled,
                        "max_order_notional": 20,
                        "max_quote_age_seconds": 60,
                        "max_spread_bps": 50,
                    },
                    {
                        "execution_profile_id": "claude",
                        "agent_provider": "CLAUDE",
                        "account_alias": "claude-agentic",
                        "broker_account_fingerprint": "1" * 16,
                        "enabled": True,
                        "max_order_notional": 20,
                        "max_quote_age_seconds": 60,
                        "max_spread_bps": 50,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def _populate(db_path: Path, config_path: Path) -> None:
    conn = connect(db_path)
    config = load_live_profiles(config_path)
    for profile in config.profiles:
        if not profile.enabled:
            continue
        snapshot = LivePortfolioSnapshot(
            portfolio_snapshot_id=f"snap_{profile.execution_profile_id}",
            execution_profile_id=profile.execution_profile_id,
            broker_account_fingerprint=profile.broker_account_fingerprint,
            captured_at=NOW
            - (
                timedelta(minutes=6)
                if profile.execution_profile_id == "claude"
                else timedelta(minutes=1)
            ),
            account_equity=110 if profile.execution_profile_id == "codex" else 95,
            buying_power=70,
            positions=[
                {
                    "ticker": "NVDA" if profile.execution_profile_id == "codex" else "MSFT",
                    "market_value": 20,
                    "primary_theme_id": "ai",
                }
            ],
        )
        save_live_portfolio_snapshot(conn, snapshot, profile)
        run = ReasoningRun(
            reasoning_run_id=f"rr_2026-08-27_close_{profile.execution_profile_id}",
            session_date=date(2026, 8, 27),
            slot="close",
            execution_profile_id=profile.execution_profile_id,
            model_label=profile.agent_provider.value.title(),
            shared_bundle_path="data/reason/2026-08-27/shared_bundle.md",
            shared_bundle_sha256="a" * 64,
            portfolio_snapshot_id=snapshot.portfolio_snapshot_id,
            started_at=NOW - timedelta(minutes=1),
        )
        save_reasoning_run(conn, run)
        if profile.execution_profile_id == "claude":
            complete_reasoning_run(
                conn,
                ReasoningRun.model_validate(
                    {
                        **run.model_dump(),
                        "result": "NO_ACTION",
                        "completed_at": NOW,
                        "public_summary": "No action <script>alert(1)</script>",
                    }
                ),
            )
    conn.execute(
        """
        INSERT INTO live_execution_packets
            (execution_packet_id, order_intent_id, execution_profile_id, created_at,
             expires_at, ticker, side, notional, limit_price, packet_json)
        VALUES ('ep_codex', 'oi_codex', 'codex', ?, ?, 'NVDA', 'BUY', 12, 200, '{}')
        """,
        ((NOW - timedelta(seconds=5)).isoformat(), (NOW + timedelta(minutes=1)).isoformat()),
    )
    conn.execute(
        """
        INSERT INTO live_execution_packets
            (execution_packet_id, order_intent_id, execution_profile_id, created_at,
             expires_at, ticker, side, notional, limit_price, packet_json)
        VALUES ('ep_expired', 'oi_expired', 'codex', ?, ?, 'NVDA', 'BUY', 12, 200, '{}')
        """,
        ((NOW - timedelta(minutes=2)).isoformat(), (NOW - timedelta(minutes=1)).isoformat()),
    )
    conn.execute(
        """
        INSERT INTO broker_execution_events
            (broker_event_id, broker_execution_record_id, order_intent_id,
             execution_packet_id, execution_profile_id, status, occurred_at, detail, event_json)
        VALUES ('event_claude', 'record_claude', 'oi_claude', 'ep_claude', 'claude',
                'FAILED', ?, '<b>rejected</b>', '{}')
        """,
        (NOW.isoformat(),),
    )
    conn.commit()


def test_live_operator_query_degrades_empty_and_projects_safe_diverged_state(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "test.db"
    config_path = _config(tmp_path / "live.json")
    conn = connect(db_path)
    profiles = public_profile_status(load_live_profiles(config_path))

    assert live_operator_status(conn, profiles, now=NOW)["shared"] is None

    _populate(db_path, config_path)
    payload = live_operator_status(conn, profiles, now=NOW)

    assert payload["shared"]["shared_bundle_sha256"] == "a" * 64
    assert [row["snapshot"]["account_equity"] for row in payload["profiles"]] == [110, 95]
    assert payload["profiles"][0]["execution_packet_id"] == "ep_codex"
    assert payload["profiles"][0]["pending_packet_count"] == 1
    assert payload["profiles"][1]["run"]["result"] == "NO_ACTION"
    assert "fingerprint" not in repr(payload)
    assert "snapshot_json" not in repr(payload)

    run = get_reasoning_run(conn, "rr_2026-08-27_close_codex")
    assert run is not None
    decision_id = f"{run.reasoning_run_id}_dec_001"
    conn.execute(
        "INSERT INTO reasoning_run_decisions VALUES (?, ?, ?)",
        (run.reasoning_run_id, decision_id, run.portfolio_snapshot_id),
    )
    complete_reasoning_run(
        conn,
        ReasoningRun.model_validate(
            {
                **run.model_dump(),
                "result": "DECISIONS_AUTHORED",
                "completed_at": NOW,
                "public_summary": "One decision.",
                "decision_ids": [decision_id],
            }
        ),
    )

    authored = live_operator_status(conn, profiles, now=NOW)
    assert authored["profiles"][0]["run"]["decision_count"] == 1


def test_live_operator_page_renders_isolated_prompts_and_escapes_private_state(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "test.db"
    config_path = _config(tmp_path / "live.json")
    _populate(db_path, config_path)
    conn = connect(db_path)
    profile = load_live_profiles(config_path).profiles[0]
    save_live_portfolio_snapshot(
        conn,
        LivePortfolioSnapshot(
            portfolio_snapshot_id="snap_codex_submission",
            execution_profile_id="codex",
            broker_account_fingerprint="0" * 16,
            captured_at=NOW,
            account_equity=111,
            buying_power=69,
        ),
        profile,
    )
    client = TestClient(create_app(db_path, live_config_path=config_path))

    response = client.get("/operate/live")

    assert response.status_code == 200
    assert "Paper operator" in response.text
    assert "Live trial" in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;b&gt;rejected&lt;/b&gt;" not in response.text
    assert "Broker lifecycle detail is withheld from the dashboard." in response.text
    codex_prompt = re.search(r"id='reasoning-codex'>(.*?)</pre>", response.text, re.DOTALL)
    assert codex_prompt is not None
    assert "rr_2026-08-27_close_codex" in codex_prompt.group(1)
    assert "snap_codex" in codex_prompt.group(1)
    assert "snap_codex_submission" not in codex_prompt.group(1)
    assert "snap_claude" not in codex_prompt.group(1)
    assert "data-copy='reasoning-codex' disabled" not in response.text
    assert "data-copy='reasoning-claude' disabled" in response.text
    assert "ep_codex" in response.text
    assert "data-copy='execution-codex' disabled" not in response.text


def test_live_operator_disables_prompts_for_disabled_profile(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    enabled_config = _config(tmp_path / "enabled.json")
    _populate(db_path, enabled_config)
    disabled_config = _config(tmp_path / "disabled.json", codex_enabled=False)

    response = TestClient(create_app(db_path, live_config_path=disabled_config)).get(
        "/operate/live"
    )

    assert "data-copy='reasoning-codex' disabled" in response.text
    assert "data-copy='execution-codex' disabled" in response.text


def test_live_operator_shows_bound_snapshot_as_ready_to_enable(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    config_path = _config(tmp_path / "live.json")
    _populate(db_path, config_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["profiles"][0]["enabled"] = False
    config_path.write_text(json.dumps(config), encoding="utf-8")

    response = TestClient(create_app(db_path, live_config_path=config_path)).get("/operate/live")

    assert "ready to enable; account bound and snapshot saved; profile disabled" in response.text
    assert "data-copy='reasoning-codex' disabled" in response.text
    assert "data-copy='execution-codex' disabled" in response.text


def test_live_operator_supports_one_enabled_codex_profile(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    config_path = _config(tmp_path / "live.json")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["profiles"] = [config["profiles"][0]]
    config_path.write_text(json.dumps(config), encoding="utf-8")
    _populate(db_path, config_path)

    response = TestClient(create_app(db_path, live_config_path=config_path)).get("/operate/live")

    assert response.status_code == 200
    assert "reasoning-codex" in response.text
    assert "data-copy='reasoning-codex' disabled" not in response.text
    assert "reasoning-claude" not in response.text
    assert "codex-agentic" not in response.text
    assert "0" * 16 not in response.text


def test_claude_is_rendered_as_disabled_future_support_even_if_configured_enabled(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "test.db"
    config_path = _config(tmp_path / "live.json")
    _populate(db_path, config_path)

    response = TestClient(create_app(db_path, live_config_path=config_path)).get("/operate/live")

    assert "Claude is disabled future support" in response.text
    assert "data-copy='reasoning-claude' disabled" in response.text
    assert "data-copy='execution-claude' disabled" in response.text


def test_reasoning_prompt_requires_the_latest_matching_shared_intake(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    config_path = _config(tmp_path / "live.json")
    _populate(db_path, config_path)
    conn = connect(db_path)
    claude_run = get_reasoning_run(conn, "rr_2026-08-27_close_claude")
    assert claude_run is not None
    mismatched = claude_run.model_copy(
        update={
            "shared_bundle_path": "data/reason/2026-08-27/replacement.md",
            "shared_bundle_sha256": "b" * 64,
        }
    )
    conn.execute(
        """
        UPDATE reasoning_runs
        SET started_at = ?, shared_bundle_sha256 = ?, run_json = ?
        WHERE reasoning_run_id = ?
        """,
        (
            (NOW + timedelta(minutes=1)).isoformat(),
            "b" * 64,
            mismatched.model_dump_json(),
            mismatched.reasoning_run_id,
        ),
    )
    conn.commit()

    response = TestClient(create_app(db_path, live_config_path=config_path)).get("/operate/live")

    assert "The reasoning run doesn&#x27;t match the latest shared intake." in response.text
    assert "data-copy='reasoning-codex' disabled" in response.text


def test_private_operator_reports_actual_runtime_attempt(tmp_path: Path) -> None:
    db = tmp_path / "source.db"
    config_path = _config(tmp_path / "profiles.json")
    _populate(db, config_path)
    conn = connect(db)
    conn.execute(
        "INSERT INTO runtime_runs VALUES "
        "('runtime', 'public', 'live/test', 'live', 'test', 'codex', '2026-08-27', "
        "'close', ?, 'rr_2026-08-27_close_codex', NULL, '{}')",
        (NOW.isoformat(),),
    )
    conn.execute(
        "INSERT INTO runtime_attempts VALUES "
        "('attempt', 'attempt-public', 'runtime', 1, 1, 'no_action', 'finished', "
        "'test-model', NULL, ?, ?, ?, NULL, 'No action')",
        (NOW.isoformat(), NOW.isoformat(), NOW.isoformat()),
    )
    conn.commit()
    payload = live_operator_status(
        conn, public_profile_status(load_live_profiles(config_path)), now=NOW
    )
    profile = next(item for item in payload["profiles"] if item["execution_profile_id"] == "codex")
    assert profile["runtime_status"] == "no_action"
    assert profile["runtime_attempts"][0]["attempt_id"] == "attempt"
    assert not profile["reasoning_ready"]
    conn.close()
    client = TestClient(create_app(db, live_config_path=config_path))
    assert "Actual runtime attempts" in client.get("/operate/live").text


def test_operator_view_counts_linked_decisions_after_successful_retry(tmp_path: Path) -> None:
    from typing import Any

    from app.reason.worker import execute_attempt
    from app.schemas.decision_record import InvestmentDecisionRecord
    from app.schemas.live_execution import LivePortfolioSnapshot
    from app.schemas.runtime import AuthoredOutput
    from app.storage.records import save_live_portfolio_snapshot
    from app.storage.runtime import save_run
    from tests.fixtures.decision_records import valid_decision_record_data
    from tests.reason.test_live_submit import _profile
    from tests.reason.test_runtime import NOW as RUNTIME_NOW
    from tests.reason.test_runtime import live_run

    db = tmp_path / "source.db"
    config_path = _config(tmp_path / "profiles.json")
    conn = connect(db)
    run = live_run(conn, tmp_path)
    save_run(conn, run)
    current = RUNTIME_NOW

    def blocked_author(prompt: str, **kwargs: Any) -> AuthoredOutput:
        namespace = prompt.split("Decision namespace: ")[1].splitlines()[0]
        record = InvestmentDecisionRecord.model_validate(
            {**valid_decision_record_data(), "decision_id": namespace + "one"}
        )
        conflict = record.model_copy(update={"public_summary": "Conflicting immutable record"})
        return AuthoredOutput(decisions=[record, conflict], public_summary="Two outputs.")

    first = execute_attempt(
        conn,
        run.run_id,
        "first-model",
        profile=_profile(),
        runner=blocked_author,
        clock=lambda: current,
        log_root=tmp_path / "logs",
    )
    assert first.status == "blocked" and first.reason == "submission_blocked"
    current += timedelta(seconds=1)
    save_live_portfolio_snapshot(
        conn,
        LivePortfolioSnapshot(
            portfolio_snapshot_id="fresh",
            execution_profile_id="codex",
            broker_account_fingerprint="0" * 16,
            captured_at=current,
            account_equity=100,
            buying_power=100,
        ),
        _profile(),
    )

    def retry_author(prompt: str, **kwargs: object) -> AuthoredOutput:
        namespace = prompt.split("Decision namespace: ")[1].splitlines()[0]
        record = InvestmentDecisionRecord.model_validate(
            {**valid_decision_record_data(), "decision_id": namespace + "retry"}
        )
        return AuthoredOutput(decisions=[record], public_summary="Fresh snapshot review.")

    retried = execute_attempt(
        conn,
        run.run_id,
        "retry-model",
        profile=_profile(),
        runner=retry_author,
        retry=True,
        clock=lambda: current,
        log_root=tmp_path / "logs",
    )
    assert retried.status == "completed"
    linked = conn.execute(
        "SELECT COUNT(*) FROM reasoning_run_decisions WHERE reasoning_run_id = ?",
        (run.reasoning_run_id,),
    ).fetchone()[0]
    assert linked == 2

    payload = live_operator_status(
        conn, public_profile_status(load_live_profiles(config_path)), now=current
    )
    profile = next(item for item in payload["profiles"] if item["execution_profile_id"] == "codex")
    assert profile["run"]["result"] == "FAILED"
    assert profile["run"]["decision_count"] == linked
    assert profile["runtime_status"] == "completed"
    conn.close()
    client = TestClient(create_app(db, live_config_path=config_path))
    body = client.get("/operate/live").text
    assert "<div class='metric-label'>Decisions</div><div class='metric-value'>2</div>" in body
