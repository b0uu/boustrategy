"""Live holding episodes read from broker snapshots, and the holdings due a thesis review."""

import json
import re
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
MAX_HEADLINES_TO_TRIAGE = 10
TRIGGER_COOLDOWN = timedelta(days=3)
DRAWDOWN_TRIGGER_PERCENT = -15.0
MANDATORY_REVIEW_RETURN_PERCENT = -40.0
TRIGGER_REASONS = frozenset(
    {"price_move", "volume_spike", "earnings_reported", "x_digest", "down_15_percent_from_cost"}
)
# The mandate requires these the same day, so no cooldown holds them back.
MANDATORY_REASONS = frozenset({"down_40_percent_from_cost", "invalidated_without_exit"})


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
    """Name every holding a review prepared at this instant must answer for, and why.

    A significant holding is due at each review point until a review recorded after that point
    covers its episode; a missed point carries to the next review that runs. A price move,
    volume spike, reported earnings or a first close below 15% under cost since its last review
    also makes it due. X headlines bearing on it since then are listed for the review to triage
    instead: only the agent, holding the thesis, can judge whether one could change it. For three
    days after a review that a trigger caused, neither the schedule nor another trigger makes it
    due and no headline is listed. Falling 40% under cost, or an invalidated verdict with no sale
    since, makes it due regardless. A holding is returned when it is due or has headlines to
    triage.
    """
    account_id = snapshot.broker_account_fingerprint
    episodes = live_holding_episodes(conn, account_id, snapshot.captured_at)
    point = latest_review_point(prepared_at)
    session_day = prepared_at.astimezone(NEW_YORK).date()
    returns: dict[str, list[tuple[datetime, float]]] = {}
    for (snapshot_json,) in conn.execute(
        "SELECT snapshot_json FROM live_portfolio_snapshots "
        "WHERE julianday(captured_at)<=julianday(?) ORDER BY julianday(captured_at)",
        (snapshot.captured_at.isoformat(),),
    ):
        earlier = LivePortfolioSnapshot.model_validate_json(snapshot_json)
        if earlier.broker_account_fingerprint != account_id or earlier.reporting is None:
            continue
        for held in earlier.reporting.positions or []:
            if held.average_cost and held.price is not None:
                returns.setdefault(held.ticker, []).append(
                    (earlier.captured_at, float(held.price / held.average_cost - 1) * 100)
                )
    due = []
    for position in snapshot.positions:
        ticker = position.ticker
        episode = episodes[ticker]
        opened_at = datetime.fromisoformat(episode["opened_at"])
        reviews = [
            json.loads(row[0])
            for row in conn.execute(
                "SELECT record_json FROM thesis_reviews WHERE mode='live' AND account_id=? "
                "AND episode_id=? AND julianday(reviewed_at)<=julianday(?) "
                "ORDER BY julianday(reviewed_at) DESC",
                (account_id, episode["episode_id"], prepared_at.isoformat()),
            )
        ]
        last_reviewed = datetime.fromisoformat(reviews[0]["reviewed_at"]) if reviews else None
        since = last_reviewed or opened_at
        reasons = []
        if position.market_value / snapshot.account_equity >= SIGNIFICANT_WEIGHT and (
            last_reviewed is None or last_reviewed < point
        ):
            reasons.append("scheduled_review")
        for trigger_type, fired_on in conn.execute(
            "SELECT DISTINCT trigger_type, fired_at FROM trigger_events WHERE subject=? "
            "AND trigger_type IN ('price_move', 'volume_spike') ORDER BY trigger_type",
            (ticker,),
        ):
            # A trigger dated for a session reflects that session's close.
            close = datetime.combine(datetime.fromisoformat(fired_on).date(), time(16), NEW_YORK)
            if since < close <= prepared_at and trigger_type not in reasons:
                reasons.append(trigger_type)
        # A date the agent read from a source outranks a feed estimate within a month of it.
        if conn.execute(
            "SELECT 1 FROM calendar_events e WHERE event_type='earnings' AND ticker=? "
            "AND event_date>=? AND event_date<? AND (source='agent' OR NOT EXISTS ("
            "SELECT 1 FROM calendar_events a WHERE a.event_type='earnings' "
            "AND a.ticker=e.ticker AND a.source='agent' "
            "AND abs(julianday(a.event_date)-julianday(e.event_date))<=30))",
            (ticker, since.astimezone(NEW_YORK).date().isoformat(), session_day.isoformat()),
        ).fetchone():
            reasons.append("earnings_reported")
        # The digester tags each post with the tickers it bears on, named or implied. Posts
        # routed before tagging existed only match on the symbol itself.
        mention = re.compile(rf"(?<![A-Za-z0-9])\$?{re.escape(ticker)}(?![A-Za-z0-9])")
        headlines = [
            {
                "post_id": post_id,
                "handle": handle,
                "url": url,
                "text": text,
                "digest_reason": reason,
            }
            for post_id, handle, url, text, reason, tickers in conn.execute(
                "SELECT p.post_id, p.handle, p.url, p.text, r.reason, r.tickers "
                "FROM x_route_decisions r JOIN x_posts p ON p.post_id=r.post_id "
                "WHERE r.rank='headline' AND julianday(r.decided_at)>julianday(?) "
                "AND julianday(r.decided_at)<=julianday(?) AND NOT EXISTS ("
                "SELECT 1 FROM x_triage t WHERE t.post_id=r.post_id AND t.ticker=? "
                "AND t.account_id=?) ORDER BY julianday(r.decided_at) DESC",
                (since.isoformat(), prepared_at.isoformat(), ticker, account_id),
            )
            if ticker in json.loads(tickers) or mention.search(text) or mention.search(reason)
        ][:MAX_HEADLINES_TO_TRIAGE]
        for threshold, reason in (
            (DRAWDOWN_TRIGGER_PERCENT, "down_15_percent_from_cost"),
            (MANDATORY_REVIEW_RETURN_PERCENT, "down_40_percent_from_cost"),
        ):
            # The start of the current stretch below the threshold, if the holding is below it.
            crossed = None
            for at, return_percent in returns.get(ticker, []):
                if at < opened_at:
                    continue
                if return_percent > threshold:
                    crossed = None
                elif crossed is None:
                    crossed = at
            if crossed is not None and since < crossed:
                reasons.append(reason)
        if (
            reviews
            and reviews[0]["state"] == "invalidated"
            and not conn.execute(
                "SELECT 1 FROM order_intents WHERE execution_mode='LIVE' "
                "AND execution_profile_id=? AND ticker=? AND side='SELL' "
                "AND julianday(created_at)>=julianday(?)",
                (snapshot.execution_profile_id, ticker, reviews[0]["reviewed_at"]),
            ).fetchone()
        ):
            reasons.append("invalidated_without_exit")
        triggered = next(
            (
                datetime.fromisoformat(review["reviewed_at"])
                for review in reviews
                if TRIGGER_REASONS.intersection(review.get("review_reasons", []))
            ),
            None,
        )
        if triggered is not None and prepared_at < triggered + TRIGGER_COOLDOWN:
            reasons = [reason for reason in reasons if reason in MANDATORY_REASONS]
            headlines = []
        if reasons or headlines:
            due.append(
                {
                    **episode,
                    "last_reviewed_at": last_reviewed.isoformat() if last_reviewed else None,
                    "reasons": reasons,
                    "x_headlines": headlines,
                }
            )
    return due
