import sqlite3

from app.schemas.decision_record import InvestmentDecisionRecord
from app.schemas.order_intent import OrderIntent


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
        raise ValueError(f"decision record {record.decision_id} already exists with different content")

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
        if existing[0] == intent_json:
            return False
        raise ValueError(
            f"order intent {intent.order_intent_id} already exists with different content"
        )

    try:
        conn.execute(
            """
            INSERT INTO order_intents
                (order_intent_id, decision_id, created_at, ticker, side, intent_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                intent.order_intent_id,
                intent.decision_id,
                intent.created_at.isoformat(),
                intent.ticker,
                intent.side.value,
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
