from datetime import UTC, datetime

import pytest

from app.orders.create_order_intent import create_order_intent
from app.policy.decision_policy import PolicyResult
from app.schemas.broker_execution import BrokerExecutionRecord
from app.schemas.live_execution import LiveExecutionPacket
from app.schemas.order_intent import ExecutionMode
from app.storage.database import connect
from app.storage.records import (
    get_broker_execution_record,
    get_decision_record,
    get_execution_packet,
    get_order_intent,
    save_broker_execution_record,
    save_decision_record,
    save_execution_packet,
    save_order_intent,
)
from tests.fixtures.decision_records import decision_record_with, valid_decision_record
from tests.fixtures.live_execution import live_execution_packet


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
        execution_profile_id="codex",
    )
    save_order_intent(conn, intent)
    save_decision_record(conn, valid_decision_record())
    save_execution_packet(conn, live_execution_packet(intent))
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
        execution_packet_id=f"ep_codex_{intent.order_intent_id}",
        execution_profile_id="codex",
        account_alias="codex-agentic",
        ticker=intent.ticker,
        side=intent.side,
        order_type=intent.order_type,
        requested_notional=12.0,
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
        execution_profile_id="codex",
    )
    save_order_intent(conn, intent)
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
        submitted_at=datetime(2026, 8, 26, 14, 0, tzinfo=UTC),
        status="FILLED",
        broker_order_id="rh_001",
        execution_price=200.0,
    )

    with pytest.raises(ValueError, match="must begin at SUBMITTED"):
        save_broker_execution_record(conn, record)


def test_execution_packet_round_trips_for_matching_live_profile() -> None:
    conn = connect(":memory:")
    intent = create_order_intent(
        valid_decision_record(),
        PolicyResult(approved=True),
        execution_mode=ExecutionMode.LIVE,
        execution_profile_id="codex",
    )
    save_order_intent(conn, intent)
    packet = LiveExecutionPacket(
        execution_packet_id="ep_codex_oi_dec_001",
        order_intent_id=intent.order_intent_id,
        decision_id=intent.decision_id,
        execution_profile_id="codex",
        agent_provider="CODEX",
        account_alias="codex-agentic",
        created_at=datetime(2026, 8, 27, 14, 0, tzinfo=UTC),
        expires_at=datetime(2026, 8, 27, 14, 0, 15, tzinfo=UTC),
        ticker=intent.ticker,
        side=intent.side,
        order_type=intent.order_type,
        target_weight=intent.target_weight,
        account_equity=100.0,
        current_position_value=0.0,
        notional=12.0,
        limit_price=200.0,
        quote_at=datetime(2026, 8, 27, 14, 0, tzinfo=UTC),
        spread_bps=10.0,
        require_human_approval=False,
    )

    save_decision_record(conn, valid_decision_record())
    assert save_execution_packet(conn, packet) is True
    assert save_execution_packet(conn, packet) is False
    assert get_execution_packet(conn, packet.execution_packet_id) == packet

    refreshed = packet.model_copy(
        update={
            "execution_packet_id": "ep_codex_oi_dec_001_refresh",
            "created_at": datetime(2026, 8, 27, 14, 1, tzinfo=UTC),
            "expires_at": datetime(2026, 8, 27, 14, 1, 15, tzinfo=UTC),
            "quote_at": datetime(2026, 8, 27, 14, 1, tzinfo=UTC),
        }
    )
    assert save_execution_packet(conn, refreshed) is True
    assert conn.execute("SELECT COUNT(*) FROM live_execution_packets").fetchone()[0] == 2
