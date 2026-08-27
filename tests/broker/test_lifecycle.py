import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from app.broker.lifecycle import append_execution_event, latest_execution_status
from app.orders.create_order_intent import create_order_intent
from app.policy.decision_policy import PolicyResult
from app.schemas.broker_execution import (
    BrokerExecutionEvent,
    BrokerExecutionRecord,
    BrokerExecutionStatus,
)
from app.schemas.order_intent import ExecutionMode, OrderIntent
from app.storage.database import connect
from app.storage.records import (
    save_broker_execution_record,
    save_execution_packet,
    save_order_intent,
)
from tests.fixtures.decision_records import valid_decision_record
from tests.fixtures.live_execution import live_execution_packet


def _live_intent(conn: sqlite3.Connection) -> OrderIntent:
    intent = create_order_intent(
        valid_decision_record(),
        PolicyResult(approved=True),
        execution_mode=ExecutionMode.LIVE,
        execution_profile_id="codex",
    )
    save_order_intent(conn, intent)
    return intent


def _event(intent_id: str, status: str, offset: int, event_id: str) -> BrokerExecutionEvent:
    return BrokerExecutionEvent(
        broker_event_id=event_id,
        broker_execution_record_id="be_001",
        order_intent_id=intent_id,
        execution_packet_id=f"ep_codex_{intent_id}",
        execution_profile_id="codex",
        status=status,
        occurred_at=datetime(2026, 8, 26, 14, 0, tzinfo=UTC) + timedelta(minutes=offset),
    )


def _save_submitted_record(conn: sqlite3.Connection, intent: OrderIntent) -> None:
    save_execution_packet(conn, live_execution_packet(intent))
    save_broker_execution_record(
        conn,
        BrokerExecutionRecord(
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
        ),
    )


def test_execution_lifecycle_is_append_only_and_idempotent() -> None:
    conn = connect(":memory:")
    intent = _live_intent(conn)
    reviewed = _event(intent.order_intent_id, "REVIEWED", 0, "event_reviewed")
    _save_submitted_record(conn, intent)
    submitted = _event(intent.order_intent_id, "SUBMITTED", 1, "event_submitted")
    filled = _event(intent.order_intent_id, "FILLED", 2, "event_filled")

    assert append_execution_event(conn, reviewed) is True
    assert append_execution_event(conn, reviewed) is False
    assert append_execution_event(conn, submitted) is True
    assert append_execution_event(conn, filled) is True

    assert latest_execution_status(conn, "be_001") == BrokerExecutionStatus.FILLED
    assert conn.execute("SELECT COUNT(*) FROM broker_execution_events").fetchone()[0] == 3


def test_submission_event_requires_persisted_execution_record() -> None:
    conn = connect(":memory:")
    intent = _live_intent(conn)
    save_execution_packet(conn, live_execution_packet(intent))
    append_execution_event(conn, _event(intent.order_intent_id, "REVIEWED", 0, "review"))

    with pytest.raises(ValueError, match="missing broker execution record"):
        append_execution_event(conn, _event(intent.order_intent_id, "SUBMITTED", 1, "submit"))


def test_execution_event_rejects_paper_intent_and_illegal_transition() -> None:
    conn = connect(":memory:")
    paper_intent = create_order_intent(valid_decision_record(), PolicyResult(approved=True))
    save_order_intent(conn, paper_intent)

    with pytest.raises(ValueError, match="is not live"):
        append_execution_event(
            conn,
            _event(paper_intent.order_intent_id, "REVIEWED", 0, "paper_review"),
        )

    live_intent = _live_intent(connect(":memory:"))
    other_conn = connect(":memory:")
    save_order_intent(other_conn, live_intent)
    with pytest.raises(ValueError, match="illegal broker transition"):
        append_execution_event(
            other_conn,
            _event(live_intent.order_intent_id, "FILLED", 0, "filled"),
        )


def test_execution_event_time_cannot_move_backward() -> None:
    conn = connect(":memory:")
    intent = _live_intent(conn)
    save_execution_packet(conn, live_execution_packet(intent))
    append_execution_event(conn, _event(intent.order_intent_id, "REVIEWED", 2, "review"))

    with pytest.raises(ValueError, match="cannot move backward"):
        append_execution_event(conn, _event(intent.order_intent_id, "FAILED", 1, "failure"))


def test_review_requires_current_execution_packet() -> None:
    conn = connect(":memory:")
    intent = _live_intent(conn)

    with pytest.raises(ValueError, match="missing execution packet"):
        append_execution_event(conn, _event(intent.order_intent_id, "REVIEWED", 0, "review"))

    save_execution_packet(conn, live_execution_packet(intent))
    expired_review = BrokerExecutionEvent(
        broker_event_id="expired_review",
        broker_execution_record_id="be_001",
        order_intent_id=intent.order_intent_id,
        execution_packet_id=f"ep_codex_{intent.order_intent_id}",
        execution_profile_id="codex",
        status="REVIEWED",
        occurred_at=datetime(2026, 8, 26, 14, 3, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="expired before broker review"):
        append_execution_event(conn, expired_review)
