import sqlite3

from app.schemas.broker_execution import BrokerExecutionRecord, BrokerExecutionStatus
from app.schemas.decision_record import InvestmentDecisionRecord
from app.schemas.live_execution import LiveExecutionPacket
from app.schemas.order_intent import ExecutionMode, OrderIntent


def save_decision_record(
    conn: sqlite3.Connection,
    record: InvestmentDecisionRecord,
) -> bool:
    record_json = record.model_dump_json()
    existing = conn.execute(
        "SELECT record_json FROM decision_records WHERE decision_id = ?",
        (record.decision_id,),
    ).fetchone()
    if existing is not None:
        if existing[0] == record_json:
            return False
        raise ValueError(
            f"decision record {record.decision_id} already exists with different content"
        )

    conn.execute(
        """
        INSERT INTO decision_records (decision_id, created_at, ticker, decision, record_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            record.decision_id,
            record.created_at.isoformat(),
            record.ticker,
            record.decision.value,
            record_json,
        ),
    )
    conn.commit()
    return True


def get_decision_record(
    conn: sqlite3.Connection,
    decision_id: str,
) -> InvestmentDecisionRecord | None:
    row = conn.execute(
        "SELECT record_json FROM decision_records WHERE decision_id = ?",
        (decision_id,),
    ).fetchone()
    if row is None:
        return None
    return InvestmentDecisionRecord.model_validate_json(row[0])


def save_order_intent(conn: sqlite3.Connection, intent: OrderIntent) -> bool:
    intent_json = intent.model_dump_json()
    existing = conn.execute(
        "SELECT intent_json FROM order_intents WHERE order_intent_id = ?",
        (intent.order_intent_id,),
    ).fetchone()
    if existing is not None:
        if OrderIntent.model_validate_json(existing[0]) == intent:
            return False
        raise ValueError(
            f"order intent {intent.order_intent_id} already exists with different content"
        )

    try:
        conn.execute(
            """
            INSERT INTO order_intents
                (order_intent_id, decision_id, created_at, ticker, side, execution_mode,
                 execution_profile_id, intent_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                intent.order_intent_id,
                intent.decision_id,
                intent.created_at.isoformat(),
                intent.ticker,
                intent.side.value,
                intent.execution_mode.value,
                intent.execution_profile_id,
                intent_json,
            ),
        )
    except sqlite3.IntegrityError as error:
        raise ValueError(
            f"decision {intent.decision_id} already has a different order intent"
        ) from error
    conn.commit()
    return True


def get_order_intent(
    conn: sqlite3.Connection,
    order_intent_id: str,
) -> OrderIntent | None:
    row = conn.execute(
        "SELECT intent_json FROM order_intents WHERE order_intent_id = ?",
        (order_intent_id,),
    ).fetchone()
    if row is None:
        return None
    return OrderIntent.model_validate_json(row[0])


def save_broker_execution_record(
    conn: sqlite3.Connection,
    record: BrokerExecutionRecord,
) -> bool:
    intent = get_order_intent(conn, record.order_intent_id)
    if intent is None:
        raise ValueError(f"missing order intent {record.order_intent_id}")
    if intent.execution_mode != ExecutionMode.LIVE:
        raise ValueError(f"order intent {record.order_intent_id} is not live")
    if intent.ticker != record.ticker or intent.side != record.side:
        raise ValueError("broker execution does not match its order intent")
    if intent.execution_profile_id != record.execution_profile_id:
        raise ValueError("broker execution profile does not match its order intent")
    if record.status != BrokerExecutionStatus.SUBMITTED:
        raise ValueError("a broker execution record must begin at SUBMITTED")

    packet_row = conn.execute(
        "SELECT packet_json FROM live_execution_packets WHERE execution_packet_id = ?",
        (record.execution_packet_id,),
    ).fetchone()
    if packet_row is None:
        raise ValueError(f"missing execution packet {record.execution_packet_id}")
    packet = LiveExecutionPacket.model_validate_json(packet_row[0])
    if (
        packet.order_intent_id != record.order_intent_id
        or packet.execution_profile_id != record.execution_profile_id
        or packet.account_alias != record.account_alias
        or packet.order_type != record.order_type
        or packet.notional != record.requested_notional
    ):
        raise ValueError("broker execution does not match its execution packet")
    if packet.limit_price != record.limit_price:
        raise ValueError("broker execution limit price does not match its execution packet")
    if record.submitted_at > packet.expires_at:
        raise ValueError("broker execution packet expired before submission")

    record_json = record.model_dump_json()
    existing = conn.execute(
        """
        SELECT record_json FROM broker_execution_records
        WHERE broker_execution_record_id = ?
        """,
        (record.broker_execution_record_id,),
    ).fetchone()
    if existing is not None:
        if BrokerExecutionRecord.model_validate_json(existing[0]) == record:
            return False
        raise ValueError(
            f"broker execution {record.broker_execution_record_id} already exists "
            "with different content"
        )

    try:
        conn.execute(
            """
            INSERT INTO broker_execution_records
                (broker_execution_record_id, order_intent_id, execution_packet_id,
                 execution_profile_id, account_alias, submitted_at, ticker, side, status,
                 broker_order_id, record_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.broker_execution_record_id,
                record.order_intent_id,
                record.execution_packet_id,
                record.execution_profile_id,
                record.account_alias,
                record.submitted_at.isoformat(),
                record.ticker,
                record.side.value,
                record.status.value,
                record.broker_order_id,
                record_json,
            ),
        )
    except sqlite3.IntegrityError as error:
        raise ValueError("order intent or broker order already has an execution record") from error
    conn.commit()
    return True


def get_broker_execution_record(
    conn: sqlite3.Connection,
    broker_execution_record_id: str,
) -> BrokerExecutionRecord | None:
    row = conn.execute(
        """
        SELECT record_json FROM broker_execution_records
        WHERE broker_execution_record_id = ?
        """,
        (broker_execution_record_id,),
    ).fetchone()
    if row is None:
        return None
    return BrokerExecutionRecord.model_validate_json(row[0])


def save_execution_packet(conn: sqlite3.Connection, packet: LiveExecutionPacket) -> bool:
    intent = get_order_intent(conn, packet.order_intent_id)
    if intent is None:
        raise ValueError(f"missing order intent {packet.order_intent_id}")
    if intent.execution_mode != ExecutionMode.LIVE:
        raise ValueError(f"order intent {packet.order_intent_id} is not live")
    if intent.execution_profile_id != packet.execution_profile_id:
        raise ValueError("execution packet profile does not match its order intent")
    if intent.ticker != packet.ticker or intent.side != packet.side:
        raise ValueError("execution packet does not match its order intent")

    packet_json = packet.model_dump_json()
    existing = conn.execute(
        "SELECT packet_json FROM live_execution_packets WHERE execution_packet_id = ?",
        (packet.execution_packet_id,),
    ).fetchone()
    if existing is not None:
        if LiveExecutionPacket.model_validate_json(existing[0]) == packet:
            return False
        raise ValueError(f"execution packet {packet.execution_packet_id} has conflicting content")
    try:
        conn.execute(
            """
            INSERT INTO live_execution_packets
                (execution_packet_id, order_intent_id, execution_profile_id, created_at,
                 expires_at, ticker, side, notional, limit_price, packet_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                packet.execution_packet_id,
                packet.order_intent_id,
                packet.execution_profile_id,
                packet.created_at.isoformat(),
                packet.expires_at.isoformat(),
                packet.ticker,
                packet.side.value,
                packet.notional,
                packet.limit_price,
                packet_json,
            ),
        )
    except sqlite3.IntegrityError as error:
        raise ValueError("execution packet conflicts with an existing packet") from error
    conn.commit()
    return True


def get_execution_packet(
    conn: sqlite3.Connection,
    execution_packet_id: str,
) -> LiveExecutionPacket | None:
    row = conn.execute(
        "SELECT packet_json FROM live_execution_packets WHERE execution_packet_id = ?",
        (execution_packet_id,),
    ).fetchone()
    if row is None:
        return None
    return LiveExecutionPacket.model_validate_json(row[0])
