"""The short watchlist as dated calls, derived from policy-approved decision records."""

import sqlite3
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.schemas.decision_record import (
    Decision,
    InvestmentDecisionRecord,
    ShortRemovalConditions,
)


class ShortDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str
    declared_at: datetime
    reference_price: float | None
    thesis_invalidation_criteria: list[str]
    removal_conditions: ShortRemovalConditions | None = None


class ShortCall(BaseModel):
    """One stretch on the short watchlist: every declaration until the call is removed."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    declarations: list[ShortDeclaration]
    removed_at: datetime | None = None
    removal_decision_id: str | None = None
    removal_price: float | None = None


def short_removal_status(call: ShortCall, latest_close: float | None, on_date: date) -> list[str]:
    """Name every removal condition an open call has already met.

    Prices are judged on completed closes, not intraday touches: the harness sees prices through
    daily bars, so an intraday rule would fire or not depending on when it happened to look.
    """
    if call.removed_at is not None:
        return []
    conditions = call.declarations[-1].removal_conditions
    if conditions is None:
        return []
    due = []
    if latest_close is not None and latest_close <= conditions.cover_below:
        due.append("cover_below_hit")
    if latest_close is not None and latest_close >= conditions.stop_above:
        due.append("stop_above_hit")
    if on_date >= conditions.review_by:
        due.append("review_by_reached")
    return due


def short_call_report(
    conn: sqlite3.Connection,
    execution_mode: str,
    execution_profile_id: str | None,
    on_date: date,
) -> list[dict[str, Any]]:
    """Score every short call: its dates, its prices, and how the short would have done.

    A short gains when the price falls, so the return is (declared - ended) / declared. An open
    call is marked to its latest close; a removed one to the price recorded at removal.
    """
    from app.prices.cache import get_daily_prices

    report = []
    for call in short_watchlist_history(conn, execution_mode, execution_profile_id):
        first, latest = call.declarations[0], call.declarations[-1]
        bars = get_daily_prices(conn, call.ticker, end=on_date)
        close = bars[-1].close if bars else None
        ended_at = (
            call.removed_at.date() if call.removed_at else (bars[-1].bar_date if bars else None)
        )
        end_price = call.removal_price if call.removed_at else close
        declared = first.reference_price
        percent = (
            (declared - end_price) / declared * 100
            if declared and end_price is not None and declared > 0
            else None
        )
        report.append(
            {
                "ticker": call.ticker,
                "status": "removed" if call.removed_at else "open",
                "declared_at": first.declared_at.date().isoformat(),
                "declared_price": declared,
                "declarations": [item.declared_at.date().isoformat() for item in call.declarations],
                "latest_declared_at": latest.declared_at.date().isoformat(),
                "removed_at": call.removed_at.date().isoformat() if call.removed_at else None,
                "end_price": end_price,
                "ended_at": ended_at.isoformat() if ended_at else None,
                "short_return_percent": round(percent, 4) if percent is not None else None,
                "days_listed": (
                    (call.removed_at.date() if call.removed_at else on_date)
                    - first.declared_at.date()
                ).days,
                "removal_conditions": latest.removal_conditions.model_dump(mode="json")
                if latest.removal_conditions
                else None,
                "due": short_removal_status(call, close, on_date),
                "decision_ids": [item.decision_id for item in call.declarations]
                + ([call.removal_decision_id] if call.removal_decision_id else []),
            }
        )
    return report


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
                    removal_conditions=record.short_removal_conditions,
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
