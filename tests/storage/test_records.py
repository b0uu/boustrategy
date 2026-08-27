from datetime import UTC, datetime

import pytest

from app.orders.create_order_intent import create_order_intent
from app.policy.decision_policy import PolicyResult
from app.schemas.broker_execution import BrokerExecutionRecord
from app.schemas.order_intent import ExecutionMode
from app.storage.database import connect
from app.storage.records import (
    get_broker_execution_record,
    get_decision_record,
    get_order_intent,
    save_broker_execution_record,
    save_decision_record,
    save_order_intent,
)
from tests.fixtures.decision_records import decision_record_with, valid_decision_record


def test_decision_record_round_trip():
    conn = connect(":memory:")
    record = valid_decision_record()

    save_decision_record(conn, record)
    loaded = get_decision_record(conn, record.decision_id)

    assert loaded == record


def test_saving_identical_record_twice_is_noop():
    conn = connect(":memory:")
    record = valid_decision_record()

    first = save_decision_record(conn, record)
    second = save_decision_record(conn, record)
    row_count = conn.execute("SELECT COUNT(*) FROM decision_records").fetchone()[0]

    assert first is True
    assert second is False
    assert row_count == 1


def test_saving_conflicting_record_raises():
    conn = connect(":memory:")
    record = valid_decision_record()
    conflicting = decision_record_with(internal_notes="changed")
    save_decision_record(conn, record)

    with pytest.raises(ValueError):
        save_decision_record(conn, conflicting)


def test_get_missing_record_returns_none():
    conn = connect(":memory:")

    loaded = get_decision_record(conn, "missing")

    assert loaded is None


def test_order_intent_round_trip():
    conn = connect(":memory:")
    intent = create_order_intent(valid_decision_record(), PolicyResult(approved=True))

    save_order_intent(conn, intent)
    loaded = get_order_intent(conn, intent.order_intent_id)

    assert loaded == intent


def test_second_intent_for_same_decision_is_rejected():
    conn = connect(":memory:")
    first = create_order_intent(valid_decision_record(), PolicyResult(approved=True))
    second = first.model_copy(update={"order_intent_id": "oi_different"})
    save_order_intent(conn, first)

    with pytest.raises(ValueError):
        save_order_intent(conn, second)


def test_database_file_created_on_connect(tmp_path):
    db_path = tmp_path / "sub" / "x.db"

    conn = connect(db_path)
    conn.close()

    assert db_path.exists()


def test_broker_execution_requires_live_intent_and_round_trips() -> None:
    conn = connect(":memory:")
    intent = create_order_intent(
        valid_decision_record(),
        PolicyResult(approved=True),
        execution_mode=ExecutionMode.LIVE,
    )
    save_order_intent(conn, intent)
    record = BrokerExecutionRecord(
        broker_execution_record_id="be_001",
        order_intent_id=intent.order_intent_id,
        ticker=intent.ticker,
        side=intent.side,
        order_type=intent.order_type,
        notional_or_quantity="$15.00 notional",
        limit_price=200.0,
        submitted_at=datetime(2026, 8, 26, 14, 0, tzinfo=UTC),
        status="SUBMITTED",
        broker_order_id="rh_001",
        execution_price=0.0,
    )

    first = save_broker_execution_record(conn, record)
    second = save_broker_execution_record(conn, record)

    assert first is True
    assert second is False
    assert get_broker_execution_record(conn, "be_001") == record


def test_broker_execution_rejects_paper_intent() -> None:
    conn = connect(":memory:")
    intent = create_order_intent(valid_decision_record(), PolicyResult(approved=True))
    save_order_intent(conn, intent)
    record = BrokerExecutionRecord(
        broker_execution_record_id="be_001",
        order_intent_id=intent.order_intent_id,
        ticker=intent.ticker,
        side=intent.side,
        order_type=intent.order_type,
        notional_or_quantity="$15.00 notional",
        limit_price=200.0,
        submitted_at=datetime(2026, 8, 26, 14, 0, tzinfo=UTC),
        status="SUBMITTED",
        broker_order_id="rh_001",
        execution_price=0.0,
    )

    with pytest.raises(ValueError, match="is not live"):
        save_broker_execution_record(conn, record)


def test_broker_execution_record_must_begin_submitted() -> None:
    conn = connect(":memory:")
    intent = create_order_intent(
        valid_decision_record(),
        PolicyResult(approved=True),
        execution_mode=ExecutionMode.LIVE,
    )
    save_order_intent(conn, intent)
    record = BrokerExecutionRecord(
        broker_execution_record_id="be_001",
        order_intent_id=intent.order_intent_id,
        ticker=intent.ticker,
        side=intent.side,
        order_type=intent.order_type,
        notional_or_quantity="$15.00 notional",
        limit_price=200.0,
        submitted_at=datetime(2026, 8, 26, 14, 0, tzinfo=UTC),
        status="FILLED",
        broker_order_id="rh_001",
        execution_price=200.0,
    )

    with pytest.raises(ValueError, match="must begin at SUBMITTED"):
        save_broker_execution_record(conn, record)
