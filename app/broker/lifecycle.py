import sqlite3
from datetime import datetime

from app.schemas.broker_execution import BrokerExecutionEvent, BrokerExecutionStatus
from app.schemas.live_execution import LiveExecutionPacket
from app.schemas.order_intent import ExecutionMode
from app.storage.records import get_broker_execution_record, get_order_intent

_LEGAL_TRANSITIONS: dict[BrokerExecutionStatus | None, set[BrokerExecutionStatus]] = {
    None: {BrokerExecutionStatus.REVIEWED, BrokerExecutionStatus.FAILED},
    BrokerExecutionStatus.REVIEWED: {
        BrokerExecutionStatus.SUBMITTED,
        BrokerExecutionStatus.CANCELED,
        BrokerExecutionStatus.FAILED,
    },
    BrokerExecutionStatus.SUBMITTED: {
        BrokerExecutionStatus.PARTIALLY_FILLED,
        BrokerExecutionStatus.FILLED,
        BrokerExecutionStatus.CANCELED,
        BrokerExecutionStatus.FAILED,
    },
    BrokerExecutionStatus.PARTIALLY_FILLED: {
        BrokerExecutionStatus.PARTIALLY_FILLED,
        BrokerExecutionStatus.FILLED,
        BrokerExecutionStatus.CANCELED,
        BrokerExecutionStatus.FAILED,
    },
    BrokerExecutionStatus.FILLED: set(),
    BrokerExecutionStatus.CANCELED: set(),
    BrokerExecutionStatus.FAILED: set(),
}


def latest_execution_status(
    conn: sqlite3.Connection,
    broker_execution_record_id: str,
) -> BrokerExecutionStatus | None:
    row = conn.execute(
        """
        SELECT status FROM broker_execution_events
        WHERE broker_execution_record_id = ?
        ORDER BY occurred_at DESC, rowid DESC LIMIT 1
        """,
        (broker_execution_record_id,),
    ).fetchone()
    return BrokerExecutionStatus(row[0]) if row is not None else None


def append_execution_event(conn: sqlite3.Connection, event: BrokerExecutionEvent) -> bool:
    intent = get_order_intent(conn, event.order_intent_id)
    if intent is None:
        raise ValueError(f"missing order intent {event.order_intent_id}")
    if intent.execution_mode != ExecutionMode.LIVE:
        raise ValueError(f"order intent {event.order_intent_id} is not live")
    if intent.execution_profile_id != event.execution_profile_id:
        raise ValueError("broker event profile does not match its order intent")

    existing = conn.execute(
        "SELECT event_json FROM broker_execution_events WHERE broker_event_id = ?",
        (event.broker_event_id,),
    ).fetchone()
    if existing is not None:
        if BrokerExecutionEvent.model_validate_json(existing[0]) == event:
            return False
        raise ValueError(f"broker event {event.broker_event_id} has conflicting content")

    current = latest_execution_status(conn, event.broker_execution_record_id)
    latest_time_row = conn.execute(
        """
        SELECT occurred_at FROM broker_execution_events
        WHERE broker_execution_record_id = ?
        ORDER BY occurred_at DESC, rowid DESC LIMIT 1
        """,
        (event.broker_execution_record_id,),
    ).fetchone()
    if latest_time_row is not None:
        latest_time = datetime.fromisoformat(latest_time_row[0])
        if event.occurred_at < latest_time:
            raise ValueError("broker event occurred_at cannot move backward")
    if event.status not in _LEGAL_TRANSITIONS[current]:
        raise ValueError(
            f"illegal broker transition from {current} to {event.status} "
            f"for {event.broker_execution_record_id}"
        )

    if event.status == BrokerExecutionStatus.REVIEWED:
        packet_row = conn.execute(
            "SELECT packet_json FROM live_execution_packets WHERE execution_packet_id = ?",
            (event.execution_packet_id,),
        ).fetchone()
        if packet_row is None:
            raise ValueError(f"missing execution packet {event.execution_packet_id}")
        packet = LiveExecutionPacket.model_validate_json(packet_row[0])
        if (
            packet.order_intent_id != event.order_intent_id
            or packet.execution_profile_id != event.execution_profile_id
        ):
            raise ValueError("broker event profile does not match its execution packet")
        if event.occurred_at > packet.expires_at:
            raise ValueError("execution packet expired before broker review")

    execution = get_broker_execution_record(conn, event.broker_execution_record_id)
    if event.status in {
        BrokerExecutionStatus.SUBMITTED,
        BrokerExecutionStatus.PARTIALLY_FILLED,
        BrokerExecutionStatus.FILLED,
        BrokerExecutionStatus.CANCELED,
    }:
        if execution is None:
            raise ValueError(f"missing broker execution record {event.broker_execution_record_id}")
        if execution.order_intent_id != event.order_intent_id:
            raise ValueError("broker event does not match its execution record")
        if execution.execution_packet_id != event.execution_packet_id:
            raise ValueError("broker event packet does not match its execution record")

    conn.execute(
        """
        INSERT INTO broker_execution_events
            (broker_event_id, broker_execution_record_id, order_intent_id,
             execution_packet_id, execution_profile_id, status, occurred_at, detail, event_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event.broker_event_id,
            event.broker_execution_record_id,
            event.order_intent_id,
            event.execution_packet_id,
            event.execution_profile_id,
            event.status.value,
            event.occurred_at.isoformat(),
            event.detail,
            event.model_dump_json(),
        ),
    )
    conn.commit()
    return True
