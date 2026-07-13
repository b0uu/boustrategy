import sqlite3
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.orders.create_order_intent import create_order_intent
from app.policy.decision_policy import PortfolioContext, evaluate_decision_policy
from app.schemas.decision_record import Decision, InvestmentDecisionRecord
from app.storage.records import (
    get_order_intent,
    save_decision_record,
    save_order_intent,
)

_ACTIONABLE_DECISIONS = {Decision.BUY, Decision.ADD, Decision.TRIM, Decision.SELL}


class DecisionStatus(StrEnum):
    DECISION_RECORD_CREATED = "decision_record_created"
    SCHEMA_VALIDATED = "schema_validated"
    SCHEMA_FAILED = "schema_failed"
    POLICY_APPROVED = "policy_approved"
    POLICY_REJECTED = "policy_rejected"
    ORDER_INTENT_CREATED = "order_intent_created"


_LEGAL_TRANSITIONS: dict[DecisionStatus | None, set[DecisionStatus]] = {
    None: {DecisionStatus.DECISION_RECORD_CREATED, DecisionStatus.SCHEMA_FAILED},
    DecisionStatus.DECISION_RECORD_CREATED: {DecisionStatus.SCHEMA_VALIDATED},
    DecisionStatus.SCHEMA_VALIDATED: {
        DecisionStatus.POLICY_APPROVED,
        DecisionStatus.POLICY_REJECTED,
    },
    DecisionStatus.POLICY_APPROVED: {DecisionStatus.ORDER_INTENT_CREATED},
    DecisionStatus.POLICY_REJECTED: set(),
    DecisionStatus.SCHEMA_FAILED: set(),
    DecisionStatus.ORDER_INTENT_CREATED: set(),
}


class ProcessOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str | None
    final_status: DecisionStatus
    policy_reasons: list[str] = Field(default_factory=list)
    order_intent_id: str | None = None


def latest_status(conn: sqlite3.Connection, subject_id: str) -> DecisionStatus | None:
    row = conn.execute(
        """
        SELECT status FROM status_events
        WHERE subject_type = 'decision' AND subject_id = ?
        ORDER BY event_id DESC LIMIT 1
        """,
        (subject_id,),
    ).fetchone()
    return DecisionStatus(row[0]) if row is not None else None


def append_status(
    conn: sqlite3.Connection,
    subject_id: str,
    status: DecisionStatus,
    detail: str = "",
) -> bool:
    rows = conn.execute(
        """
        SELECT status FROM status_events
        WHERE subject_type = 'decision' AND subject_id = ?
        ORDER BY event_id
        """,
        (subject_id,),
    ).fetchall()
    history = [DecisionStatus(row[0]) for row in rows]
    latest = history[-1] if history else None

    # Idempotent resume: a status already present in this subject's history
    # (whether the latest one or an earlier stage being replayed) is a no-op.
    if status in history:
        return False

    if status not in _LEGAL_TRANSITIONS[latest]:
        raise ValueError(f"illegal status transition from {latest} to {status} for {subject_id}")

    conn.execute(
        """
        INSERT INTO status_events (subject_type, subject_id, status, occurred_at, detail)
        VALUES ('decision', ?, ?, ?, ?)
        """,
        (subject_id, status.value, datetime.now(UTC).isoformat(), detail),
    )
    conn.commit()
    return True


def process_decision(
    conn: sqlite3.Connection,
    record_data: dict[str, Any],
    portfolio: PortfolioContext | None = None,
) -> ProcessOutcome:
    try:
        record = InvestmentDecisionRecord.model_validate(record_data)
    except ValidationError as error:
        raw_decision_id = record_data.get("decision_id")
        decision_id = (
            raw_decision_id if isinstance(raw_decision_id, str) and raw_decision_id else None
        )
        if decision_id is not None:
            append_status(conn, decision_id, DecisionStatus.SCHEMA_FAILED, detail=str(error)[:500])
        return ProcessOutcome(decision_id=decision_id, final_status=DecisionStatus.SCHEMA_FAILED)

    save_decision_record(conn, record)
    append_status(conn, record.decision_id, DecisionStatus.DECISION_RECORD_CREATED)
    append_status(conn, record.decision_id, DecisionStatus.SCHEMA_VALIDATED)

    policy_result = evaluate_decision_policy(record, portfolio)
    if not policy_result.approved:
        append_status(
            conn,
            record.decision_id,
            DecisionStatus.POLICY_REJECTED,
            detail=", ".join(policy_result.reasons),
        )
        return ProcessOutcome(
            decision_id=record.decision_id,
            final_status=DecisionStatus.POLICY_REJECTED,
            policy_reasons=policy_result.reasons,
        )

    append_status(conn, record.decision_id, DecisionStatus.POLICY_APPROVED)

    if record.decision not in _ACTIONABLE_DECISIONS:
        return ProcessOutcome(
            decision_id=record.decision_id,
            final_status=DecisionStatus.POLICY_APPROVED,
        )

    order_intent_id = f"oi_{record.decision_id}"
    intent = get_order_intent(conn, order_intent_id)
    if intent is None:
        intent = create_order_intent(record, policy_result)
        save_order_intent(conn, intent)

    append_status(conn, record.decision_id, DecisionStatus.ORDER_INTENT_CREATED)

    return ProcessOutcome(
        decision_id=record.decision_id,
        final_status=DecisionStatus.ORDER_INTENT_CREATED,
        order_intent_id=intent.order_intent_id,
    )
