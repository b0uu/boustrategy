"""The watchlist as open entries, derived from policy-approved decision records."""

import sqlite3
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.decision_record import Decision, InvestmentDecisionRecord

# An entry stands until the review acts on the ticker or drops it outright.
_CLOSING = {Decision.BUY, Decision.ADD, Decision.PASS}


class WatchlistEntry(BaseModel):
    """One stretch on the watchlist: the first listing, and the bounds of the latest statement."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    decision_id: str
    listed_at: datetime
    restated_at: datetime
    statements: int
    entry_price_min: float | None
    entry_price_max: float | None


def open_watchlist_entries(
    conn: sqlite3.Connection, execution_mode: str, execution_profile_id: str | None = None
) -> dict[str, WatchlistEntry]:
    """Every ticker currently on the watchlist, keyed by ticker.

    The watchlist is not stored separately: an entry opens at its first WATCHLIST, is restated by
    every later one, and closes when the ticker is bought, added to, or passed on.
    """
    rows = conn.execute(
        """
        SELECT d.record_json
        FROM decision_records d JOIN policy_evaluations e ON e.decision_id = d.decision_id
        WHERE d.decision IN ('WATCHLIST', 'BUY', 'ADD', 'PASS')
          AND json_extract(e.evaluation_json, '$.approved') = 1
          AND json_extract(e.evaluation_json, '$.execution_mode') = ?
          AND (? IS NULL OR json_extract(e.evaluation_json, '$.execution_profile_id') = ?)
        ORDER BY julianday(d.created_at), d.decision_id
        """,
        (execution_mode, execution_profile_id, execution_profile_id),
    ).fetchall()
    entries: dict[str, WatchlistEntry] = {}
    for (record_json,) in rows:
        record = InvestmentDecisionRecord.model_validate_json(record_json)
        if record.decision in _CLOSING:
            entries.pop(record.ticker, None)
            continue
        listed = entries.get(record.ticker)
        entries[record.ticker] = WatchlistEntry(
            ticker=record.ticker,
            decision_id=record.decision_id,
            listed_at=listed.listed_at if listed else record.created_at,
            restated_at=record.created_at,
            statements=listed.statements + 1 if listed else 1,
            entry_price_min=record.entry_price_min,
            entry_price_max=record.entry_price_max,
        )
    return entries
