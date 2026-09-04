import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.broker.run import main
from app.orders.create_order_intent import create_order_intent
from app.policy.decision_policy import PolicyResult
from app.schemas.broker_execution import BrokerExecutionEvent, BrokerExecutionRecord
from app.schemas.order_intent import ExecutionMode, OrderIntent
from app.storage.database import connect
from app.storage.records import save_decision_record, save_execution_packet, save_order_intent
from tests.fixtures.decision_records import valid_decision_record
from tests.fixtures.live_execution import live_execution_packet


def _live_intent(db_path: Path) -> OrderIntent:
    conn = connect(db_path)
    record = valid_decision_record()
    intent = create_order_intent(
        record,
        PolicyResult(approved=True),
        execution_mode=ExecutionMode.LIVE,
        execution_profile_id="codex",
    )
    save_decision_record(conn, record)
    save_order_intent(conn, intent)
    return intent


def test_broker_cli_records_submission_and_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = tmp_path / "broker.db"
    intent = _live_intent(db_path)
    save_execution_packet(connect(db_path), live_execution_packet(intent))
    record = BrokerExecutionRecord(
        broker_execution_record_id="be_001",
        order_intent_id=intent.order_intent_id,
        execution_packet_id=f"ep_codex_{intent.order_intent_id}",
        execution_profile_id="codex",
        account_alias="codex-agentic",
        ticker=intent.ticker,
        side=intent.side,
        order_type=intent.order_type,
        requested_notional=12.0,
        limit_price=200.0,
        submitted_at=datetime(2026, 8, 26, 14, 1, tzinfo=UTC),
        status="SUBMITTED",
        broker_order_id="rh_001",
        execution_price=0.0,
    )
    reviewed = BrokerExecutionEvent(
        broker_event_id="reviewed",
        broker_execution_record_id="be_001",
        order_intent_id=intent.order_intent_id,
        execution_packet_id=f"ep_codex_{intent.order_intent_id}",
        execution_profile_id="codex",
        status="REVIEWED",
        occurred_at=datetime(2026, 8, 26, 14, 0, tzinfo=UTC),
    )
    record_path = tmp_path / "record.json"
    event_path = tmp_path / "event.json"
    record_path.write_text(record.model_dump_json(), encoding="utf-8")
    event_path.write_text(reviewed.model_dump_json(), encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        ["app.broker.run", "--db", str(db_path), "event", "--in", str(event_path)],
    )
    main()
    event_result = json.loads(capsys.readouterr().out)
    monkeypatch.setattr(
        sys,
        "argv",
        ["app.broker.run", "--db", str(db_path), "record", "--in", str(record_path)],
    )
    main()
    record_result = json.loads(capsys.readouterr().out)

    assert event_result == {"created": True, "broker_event_id": "reviewed"}
    assert record_result == {"created": True, "broker_execution_record_id": "be_001"}


def test_broker_cli_builds_packet_without_placing_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = tmp_path / "broker.db"
    intent = _live_intent(db_path)
    profiles_path = tmp_path / "profiles.json"
    preflight_path = tmp_path / "preflight.json"
    profiles_path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "execution_profile_id": "codex",
                        "agent_provider": "CODEX",
                        "account_alias": "codex-agentic",
                        "broker_account_fingerprint": "0123456789abcdef",
                        "enabled": True,
                        "max_order_notional": 20.0,
                        "max_quote_age_seconds": 60,
                        "max_spread_bps": 50.0,
                        "require_human_approval": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    preflight_path.write_text(
        json.dumps(
            {
                "execution_profile_id": "codex",
                "broker_account_fingerprint": "0123456789abcdef",
                "account_equity": 100.0,
                "buying_power": 100.0,
                "current_position_value": 0.0,
                "bid": 199.9,
                "ask": 200.1,
                "quote_at": datetime.now(UTC).isoformat(),
                "tradable": True,
                "fractionable": True,
                "regular_market_hours": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "app.broker.run",
            "--db",
            str(db_path),
            "packet",
            "--intent-id",
            intent.order_intent_id,
            "--profiles",
            str(profiles_path),
            "--preflight",
            str(preflight_path),
        ],
    )

    main()

    result = json.loads(capsys.readouterr().out)
    assert result["created"] is True
    assert result["packet"]["execution_profile_id"] == "codex"
    assert result["packet"]["notional"] == 12.0


def test_broker_cli_fingerprints_account_without_storing_identifier(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["app.broker.run", "fingerprint-account"])
    monkeypatch.setattr("app.broker.run.getpass.getpass", lambda _: "sensitive-account-id")

    main()

    fingerprint = capsys.readouterr().out.strip()
    assert len(fingerprint) == 16
    assert "sensitive-account-id" not in fingerprint
