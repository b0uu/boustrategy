import sqlite3

from app.schemas.broker_execution import BrokerExecutionRecord, BrokerExecutionStatus
from app.schemas.decision_record import InvestmentDecisionRecord
from app.schemas.live_execution import (
    ExecutionProfile,
    LiveExecutionPacket,
    LivePortfolioSnapshot,
)
from app.schemas.order_intent import ExecutionMode, OrderIntent
from app.schemas.reasoning_run import ReasoningRun, ReasoningRunResult


def save_live_portfolio_snapshot(
    conn: sqlite3.Connection,
    snapshot: LivePortfolioSnapshot,
    profile: ExecutionProfile,
) -> bool:
    if not profile.enabled:
        raise ValueError("execution profile is disabled")
    if snapshot.execution_profile_id != profile.execution_profile_id:
        raise ValueError("snapshot profile does not match execution profile")
    if snapshot.broker_account_fingerprint != profile.broker_account_fingerprint:
        raise ValueError("snapshot account does not match execution profile")
    snapshot_json = snapshot.model_dump_json()
    existing = conn.execute(
        "SELECT snapshot_json FROM live_portfolio_snapshots WHERE portfolio_snapshot_id = ?",
        (snapshot.portfolio_snapshot_id,),
    ).fetchone()
    if existing is not None:
        if LivePortfolioSnapshot.model_validate_json(existing[0]) == snapshot:
            return False
        raise ValueError("portfolio snapshot already exists with different content")
    conn.execute(
        """
        INSERT INTO live_portfolio_snapshots
            (portfolio_snapshot_id, execution_profile_id, captured_at, account_equity,
             snapshot_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            snapshot.portfolio_snapshot_id,
            snapshot.execution_profile_id,
            snapshot.captured_at.isoformat(),
            snapshot.account_equity,
            snapshot_json,
        ),
    )
    conn.commit()
    return True


def get_live_portfolio_snapshot(
    conn: sqlite3.Connection, portfolio_snapshot_id: str
) -> LivePortfolioSnapshot | None:
    row = conn.execute(
        "SELECT snapshot_json FROM live_portfolio_snapshots WHERE portfolio_snapshot_id = ?",
        (portfolio_snapshot_id,),
    ).fetchone()
    return LivePortfolioSnapshot.model_validate_json(row[0]) if row else None


def save_reasoning_run(conn: sqlite3.Connection, run: ReasoningRun) -> bool:
    run_json = run.model_dump_json()
    existing = conn.execute(
        "SELECT run_json FROM reasoning_runs WHERE reasoning_run_id = ?",
        (run.reasoning_run_id,),
    ).fetchone()
    if existing is not None:
        if ReasoningRun.model_validate_json(existing[0]) == run:
            return False
        raise ValueError("reasoning run already exists with different content")
    try:
        conn.execute(
            """
            INSERT INTO reasoning_runs
                (reasoning_run_id, session_date, slot, execution_profile_id, model_label,
                 shared_bundle_sha256, portfolio_snapshot_id, result, started_at,
                 completed_at, run_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.reasoning_run_id,
                run.session_date.isoformat(),
                run.slot,
                run.execution_profile_id,
                run.model_label,
                run.shared_bundle_sha256,
                run.portfolio_snapshot_id,
                run.result.value,
                run.started_at.isoformat(),
                None,
                run_json,
            ),
        )
    except sqlite3.IntegrityError as error:
        raise ValueError(
            "reasoning run conflicts with an existing date, slot, or profile"
        ) from error
    conn.commit()
    return True


def get_reasoning_run(conn: sqlite3.Connection, reasoning_run_id: str) -> ReasoningRun | None:
    row = conn.execute(
        "SELECT run_json FROM reasoning_runs WHERE reasoning_run_id = ?",
        (reasoning_run_id,),
    ).fetchone()
    return ReasoningRun.model_validate_json(row[0]) if row else None


def complete_reasoning_run(conn: sqlite3.Connection, completed_run: ReasoningRun) -> ReasoningRun:
    existing = get_reasoning_run(conn, completed_run.reasoning_run_id)
    if existing is None:
        raise ValueError("missing reasoning run")
    if existing == completed_run:
        return existing
    if existing.result != ReasoningRunResult.PREPARED:
        raise ValueError("reasoning run is already complete")
    immutable_fields = (
        "session_date",
        "slot",
        "execution_profile_id",
        "model_label",
        "shared_bundle_path",
        "shared_bundle_sha256",
        "portfolio_snapshot_id",
        "started_at",
    )
    if any(getattr(existing, field) != getattr(completed_run, field) for field in immutable_fields):
        raise ValueError("completed reasoning run changes immutable content")
    if completed_run.result == ReasoningRunResult.PREPARED:
        raise ValueError("completion requires a terminal result")
    linked_decision_ids = {
        row[0]
        for row in conn.execute(
            "SELECT decision_id FROM reasoning_run_decisions WHERE reasoning_run_id = ?",
            (completed_run.reasoning_run_id,),
        )
    }
    if set(completed_run.decision_ids) != linked_decision_ids:
        raise ValueError("completed reasoning run decision_ids do not match linked decisions")
    conn.execute(
        """
        UPDATE reasoning_runs SET result = ?, completed_at = ?, run_json = ?
        WHERE reasoning_run_id = ? AND result = 'PREPARED'
        """,
        (
            completed_run.result.value,
            completed_run.completed_at.isoformat() if completed_run.completed_at else None,
            completed_run.model_dump_json(),
            completed_run.reasoning_run_id,
        ),
    )
    conn.commit()
    return completed_run


def save_decision_record(
    conn: sqlite3.Connection,
    record: InvestmentDecisionRecord,
    *,
    commit: bool = True,
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
    if commit:
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


def save_order_intent(
    conn: sqlite3.Connection, intent: OrderIntent, *, commit: bool = True
) -> bool:
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
    if commit:
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
