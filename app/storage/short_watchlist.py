"""The short watchlist as dated calls, derived from policy-approved decision records."""

import sqlite3
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.decision_record import Decision, InvestmentDecisionRecord


class ShortDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str
    declared_at: datetime
    reference_price: float | None
    thesis_invalidation_criteria: list[str]


class ShortCall(BaseModel):
    """One stretch on the short watchlist: every declaration until the call is removed."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    declarations: list[ShortDeclaration]
    removed_at: datetime | None = None
    removal_decision_id: str | None = None
    removal_price: float | None = None


def short_watchlist_history(
    conn: sqlite3.Connection, execution_mode: str, execution_profile_id: str | None = None
) -> list[ShortCall]:
    rows = conn.execute(
        """
        SELECT d.record_json
        FROM decision_records d JOIN policy_evaluations e ON e.decision_id = d.decision_id
        WHERE d.decision IN ('SHORT_WATCHLIST', 'SHORT_WATCHLIST_REMOVE')
          AND json_extract(e.evaluation_json, '$.approved') = 1
          AND json_extract(e.evaluation_json, '$.execution_mode') = ?
          AND (? IS NULL OR json_extract(e.evaluation_json, '$.execution_profile_id') = ?)
        ORDER BY julianday(d.created_at), d.decision_id
        """,
        (execution_mode, execution_profile_id, execution_profile_id),
    ).fetchall()
    calls: list[ShortCall] = []
    open_calls: dict[str, ShortCall] = {}
    for (record_json,) in rows:
        record = InvestmentDecisionRecord.model_validate_json(record_json)
        call = open_calls.get(record.ticker)
        if record.decision == Decision.SHORT_WATCHLIST:
            if call is None:
                call = ShortCall(ticker=record.ticker, declarations=[])
                open_calls[record.ticker] = call
                calls.append(call)
            call.declarations.append(
                ShortDeclaration(
                    decision_id=record.decision_id,
                    declared_at=record.created_at,
                    reference_price=record.reference_price,
                    thesis_invalidation_criteria=record.thesis_invalidation_criteria,
                )
            )
        # Policy rejects removing an unlisted ticker when it has context; a removal approved
        # without that context has nothing to close.
        elif call is not None:
            call.removed_at = record.created_at
            call.removal_decision_id = record.decision_id
            call.removal_price = record.reference_price
            del open_calls[record.ticker]
    return calls
