import sqlite3
from datetime import UTC, date, datetime, time, timedelta

from app.policy.decision_policy import PortfolioContext
from app.schemas.live_execution import LivePortfolioSnapshot
from app.storage.crisis import crisis_reasons
from app.storage.short_watchlist import short_watchlist_history
from app.storage.watchlist import open_watchlist_entries
from app.x.calendar import NEW_YORK


def live_portfolio_context(
    conn: sqlite3.Connection,
    snapshot: LivePortfolioSnapshot,
    on_date: date,
    exclude_ticker: str | None = None,
    funded_by_sale: bool = False,
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
    swap_buys = conn.execute(
        """
        SELECT COUNT(*) FROM order_intents o JOIN swap_pairs s ON s.buy_decision_id = o.decision_id
        WHERE o.execution_mode = 'LIVE' AND o.execution_profile_id = ?
          AND julianday(o.created_at) >= julianday(?) AND julianday(o.created_at) < julianday(?)
        """,
        (snapshot.execution_profile_id, start.isoformat(), end.isoformat()),
    ).fetchone()[0]
    return PortfolioContext(
        holdings_count=len(positions),
        buy_add_trades_today=counts.get("BUY", 0),
        swap_buy_trades_today=swap_buys,
        funded_by_same_review_sale=funded_by_sale,
        crisis_mode=bool(crisis_reasons(conn, snapshot, snapshot.captured_at)),
        sell_trim_trades_today=counts.get("SELL", 0),
        primary_theme_weights=theme_weights,
        short_watchlist_tickers=sorted(
            call.ticker
            for call in short_watchlist_history(conn, "LIVE", snapshot.execution_profile_id)
            if call.removed_at is None
        ),
        watchlist_entries={
            ticker: entry.entry_price_max
            for ticker, entry in open_watchlist_entries(
                conn, "LIVE", snapshot.execution_profile_id
            ).items()
        },
    )
