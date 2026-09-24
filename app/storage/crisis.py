"""Whether the market is in the kind of stress that changes how reviews and exits work."""

import sqlite3
from datetime import datetime, time
from typing import Any

from app.schemas.live_execution import LivePortfolioSnapshot
from app.x.calendar import NEW_YORK

CRISIS_DROP = -0.03
MARKET_INDEXES = ("SPY", "QQQ")


def crisis_reasons(
    conn: sqlite3.Connection, snapshot: LivePortfolioSnapshot, as_of: datetime
) -> list[str]:
    """Name every sign of market stress as of this instant; none means calm.

    A 3% drop in SPY or QQQ at the last close or since it, a 3% drop in account equity since the
    last session, or a raw regime that has left GREEN while the published one, which waits for
    two agreeing closes, still says GREEN.
    """
    today = as_of.astimezone(NEW_YORK).date()
    reasons = []
    for index in MARKET_INDEXES:
        closes = [
            close
            for (close,) in conn.execute(
                "SELECT close FROM daily_prices WHERE ticker=? AND bar_date<? "
                "ORDER BY bar_date DESC LIMIT 2",
                (index, today.isoformat()),
            )
        ]
        if len(closes) == 2 and closes[0] / closes[1] - 1 <= CRISIS_DROP:
            reasons.append(f"{index.lower()}_fell_3_percent_at_the_last_close")
        price = snapshot.index_prices.get(index)
        if closes and price is not None and price / closes[0] - 1 <= CRISIS_DROP:
            reasons.append(f"{index.lower()}_down_3_percent_today")
    session_open = datetime.combine(today, time(9, 30), NEW_YORK)
    prior = conn.execute(
        "SELECT account_equity FROM live_portfolio_snapshots WHERE execution_profile_id=? "
        "AND julianday(captured_at)<julianday(?) ORDER BY julianday(captured_at) DESC LIMIT 1",
        (snapshot.execution_profile_id, session_open.isoformat()),
    ).fetchone()
    if (
        prior
        and snapshot.captured_at >= session_open
        and (snapshot.account_equity / prior[0] - 1 <= CRISIS_DROP)
    ):
        reasons.append("account_down_3_percent_today")
    regime = conn.execute(
        "SELECT regime, raw_regime FROM regime_snapshots WHERE snapshot_date<=? "
        "ORDER BY snapshot_date DESC LIMIT 1",
        (today.isoformat(),),
    ).fetchone()
    if regime and regime[0] == "GREEN" and regime[1] != "GREEN":
        reasons.append("raw_regime_off_green")
    return reasons


# risk_posture.md's invested-exposure targets. They are answered, not enforced: above one, the
# review must say whether it reduces or holds, and why.
EXPOSURE_BANDS = {"GREEN": (0.80, 1.00), "YELLOW": (0.40, 0.70), "RED": (0.00, 0.20)}
BETA_SESSIONS = 60


def exposure_check(
    conn: sqlite3.Connection, snapshot: LivePortfolioSnapshot, as_of: datetime
) -> dict[str, Any]:
    """Invested exposure against the band of both the published and the raw regime.

    The published regime waits for two agreeing closes, so the raw one is weighed too: exposure
    above either band is over-exposed.
    """
    invested = sum(position.market_value for position in snapshot.positions) / (
        snapshot.account_equity
    )
    regime = conn.execute(
        "SELECT regime, raw_regime FROM regime_snapshots WHERE snapshot_date<=? "
        "ORDER BY snapshot_date DESC LIMIT 1",
        (as_of.astimezone(NEW_YORK).date().isoformat(),),
    ).fetchone()
    published, raw = regime if regime else ("GREEN", "GREEN")
    return {
        "invested_percent": round(invested * 100, 1),
        "published_regime": published,
        "published_band_percent": [round(end * 100) for end in EXPOSURE_BANDS[published]],
        "raw_regime": raw,
        "raw_band_percent": [round(end * 100) for end in EXPOSURE_BANDS[raw]],
        "over_exposed": invested > min(EXPOSURE_BANDS[published][1], EXPOSURE_BANDS[raw][1]),
    }


def market_relative_move(
    conn: sqlite3.Connection, snapshot: LivePortfolioSnapshot, ticker: str, as_of: datetime
) -> dict[str, float | None]:
    """A holding's move since the last close, QQQ's, and the part beta to QQQ doesn't explain."""
    today = as_of.astimezone(NEW_YORK).date().isoformat()

    def closes(symbol: str) -> dict[str, float]:
        return dict(
            conn.execute(
                "SELECT bar_date, close FROM daily_prices WHERE ticker=? AND bar_date<? "
                "ORDER BY bar_date DESC LIMIT ?",
                (symbol, today, BETA_SESSIONS + 1),
            ).fetchall()
        )

    own, market = closes(ticker), closes("QQQ")
    price = next(
        (
            float(position.price)
            for position in (snapshot.reporting.positions or [] if snapshot.reporting else [])
            if position.ticker == ticker and position.price is not None
        ),
        None,
    )
    index = snapshot.index_prices.get("QQQ")
    last_own = own[max(own)] if own else None
    last_market = market[max(market)] if market else None
    move = (price / last_own - 1) * 100 if price and last_own else None
    market_move = (index / last_market - 1) * 100 if index and last_market else None
    dates = sorted(set(own) & set(market))
    pairs = [
        (own[now] / own[before] - 1, market[now] / market[before] - 1)
        for before, now in zip(dates, dates[1:], strict=False)
    ]
    beta = None
    if len(pairs) >= 20:
        mean_own = sum(pair[0] for pair in pairs) / len(pairs)
        mean_market = sum(pair[1] for pair in pairs) / len(pairs)
        variance = sum((pair[1] - mean_market) ** 2 for pair in pairs)
        if variance:
            beta = sum((pair[0] - mean_own) * (pair[1] - mean_market) for pair in pairs) / variance
    excess = (
        move - beta * market_move
        if move is not None and market_move is not None and beta is not None
        else None
    )
    return {
        "move_since_last_close_percent": round(move, 2) if move is not None else None,
        "qqq_move_since_last_close_percent": round(market_move, 2)
        if market_move is not None
        else None,
        "beta_to_qqq": round(beta, 2) if beta is not None else None,
        "excess_move_percent": round(excess, 2) if excess is not None else None,
    }
