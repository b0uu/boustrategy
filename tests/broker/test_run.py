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
from app.storage.records import save_order_intent
from tests.fixtures.decision_records import valid_decision_record


def _live_intent(db_path: Path) -> OrderIntent:
    conn = connect(db_path)
    intent = create_order_intent(
        valid_decision_record(),
        PolicyResult(approved=True),
        execution_mode=ExecutionMode.LIVE,
    )
    save_order_intent(conn, intent)
    return intent


def test_broker_cli_records_submission_and_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = tmp_path / "broker.db"
    intent = _live_intent(db_path)
    record = BrokerExecutionRecord(
        broker_execution_record_id="be_001",
        order_intent_id=intent.order_intent_id,
        ticker=intent.ticker,
        side=intent.side,
        order_type=intent.order_type,
        notional_or_quantity="$15.00 notional",
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
