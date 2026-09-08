import sqlite3
from datetime import UTC, date, datetime, time, timedelta

from app.policy.decision_policy import PortfolioContext
from app.schemas.live_execution import LivePortfolioSnapshot
from app.x.calendar import NEW_YORK


def live_portfolio_context(
    conn: sqlite3.Connection,
    snapshot: LivePortfolioSnapshot,
    on_date: date,
    exclude_ticker: str | None = None,
) -> PortfolioContext:
    positions = [position for position in snapshot.positions if position.market_value > 0]
    missing_themes = [position.ticker for position in positions if not position.primary_theme_id]
    if missing_themes:
        raise ValueError(f"positions missing primary theme: {','.join(missing_themes)}")

    total_position_value = sum(position.market_value for position in positions)
    floating_point_tolerance = max(1e-6, snapshot.account_equity * 1e-9)
    if total_position_value > snapshot.account_equity + floating_point_tolerance:
        raise ValueError("position value exceeds account equity")

    theme_weights: dict[str, float] = {}
    for position in positions:
        if position.ticker != exclude_ticker:
            theme = position.primary_theme_id
            theme_weights[theme] = (
                theme_weights.get(theme, 0.0) + position.market_value / snapshot.account_equity
            )

    start = datetime.combine(on_date, time.min, NEW_YORK).astimezone(UTC)
    end = datetime.combine(on_date + timedelta(days=1), time.min, NEW_YORK).astimezone(UTC)
    counts = dict(
        conn.execute(
            """
            SELECT side, COUNT(*) FROM order_intents
            WHERE execution_mode = 'LIVE' AND execution_profile_id = ?
              AND julianday(created_at) >= julianday(?) AND julianday(created_at) < julianday(?)
            GROUP BY side
            """,
            (snapshot.execution_profile_id, start.isoformat(), end.isoformat()),
        ).fetchall()
    )
    return PortfolioContext(
        holdings_count=len(positions),
        buy_add_trades_today=counts.get("BUY", 0),
        sell_trim_trades_today=counts.get("SELL", 0),
        primary_theme_weights=theme_weights,
    )
