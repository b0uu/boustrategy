"""Live holding episodes read from broker snapshots, and the holdings due a thesis review."""

import sqlite3
from datetime import datetime, time, timedelta
from typing import Any

from app.schemas.live_execution import LivePortfolioSnapshot
from app.x.calendar import NEW_YORK

# Monday, Wednesday and Friday. Each point falls before that day's review slot is prepared
# (morning 10:00, midday 13:00), so the Monday morning, Wednesday midday and Friday midday
# reviews are the ones that must cover every holding, while they can still trade on it.
REVIEW_POINTS = ((0, time(9)), (2, time(12)), (4, time(12)))
SIGNIFICANT_WEIGHT = 0.02
MANDATORY_REVIEW_RETURN_PERCENT = -40.0


def live_holding_episodes(
    conn: sqlite3.Connection, account_id: str, as_of: datetime
) -> dict[str, dict[str, str]]:
    """Open episodes by ticker.

    An episode opens at the first snapshot that holds a ticker after one that didn't. A sale
    and rebuy between two snapshots reads as one episode.
    """
    opened: dict[str, datetime] = {}
    for (snapshot_json,) in conn.execute(
        "SELECT snapshot_json FROM live_portfolio_snapshots "
        "WHERE julianday(captured_at)<=julianday(?) ORDER BY julianday(captured_at)",
        (as_of.isoformat(),),
    ):
        snapshot = LivePortfolioSnapshot.model_validate_json(snapshot_json)
        if snapshot.broker_account_fingerprint != account_id:
            continue
        opened = {
            position.ticker: opened.get(position.ticker, snapshot.captured_at)
            for position in snapshot.positions
            if position.market_value > 0
        }
    return {
        ticker: {
            "episode_id": f"live:{account_id}:{ticker}:{at.isoformat()}",
            "ticker": ticker,
            "opened_at": at.isoformat(),
        }
        for ticker, at in sorted(opened.items())
    }


def latest_review_point(moment: datetime) -> datetime:
    local = moment.astimezone(NEW_YORK)
    for days_back in range(8):
        day = local.date() - timedelta(days=days_back)
        for weekday, at in REVIEW_POINTS:
            point = datetime.combine(day, at, NEW_YORK)
            if day.weekday() == weekday and point <= local:
                return point
    raise AssertionError("every week has a review point")


def holdings_due(
    conn: sqlite3.Connection, snapshot: LivePortfolioSnapshot, prepared_at: datetime
) -> list[dict[str, Any]]:
    """Name every holding a review prepared at this instant must thesis-review, and why.

    A significant holding is due at each review point until a review recorded after that point
    covers its episode; a missed point carries to the next review that runs. A holding down 40%
    from its cost is due in every session until reviewed that session, as the mandate requires.
    """
    account_id = snapshot.broker_account_fingerprint
    episodes = live_holding_episodes(conn, account_id, snapshot.captured_at)
    point = latest_review_point(prepared_at)
    session_day = prepared_at.astimezone(NEW_YORK).date()
    costs = {
        position.ticker: position
        for position in (snapshot.reporting.positions or [] if snapshot.reporting else [])
    }
    due = []
    for position in snapshot.positions:
        episode = episodes[position.ticker]
        row = conn.execute(
            "SELECT reviewed_at FROM thesis_reviews WHERE mode='live' AND account_id=? "
            "AND episode_id=? AND julianday(reviewed_at)<=julianday(?) "
            "ORDER BY julianday(reviewed_at) DESC LIMIT 1",
            (account_id, episode["episode_id"], prepared_at.isoformat()),
        ).fetchone()
        last_reviewed = datetime.fromisoformat(row[0]) if row else None
        reasons = []
        if position.market_value / snapshot.account_equity >= SIGNIFICANT_WEIGHT and (
            last_reviewed is None or last_reviewed < point
        ):
            reasons.append("scheduled_review")
        cost = costs.get(position.ticker)
        if (
            cost is not None
            and cost.average_cost
            and cost.price is not None
            and float(cost.price / cost.average_cost - 1) * 100 <= MANDATORY_REVIEW_RETURN_PERCENT
            and (last_reviewed is None or last_reviewed.astimezone(NEW_YORK).date() < session_day)
        ):
            reasons.append("down_40_percent_from_cost")
        if reasons:
            due.append(
                {
                    **episode,
                    "last_reviewed_at": last_reviewed.isoformat() if last_reviewed else None,
                    "reasons": reasons,
                }
            )
    return due
