import sqlite3
from datetime import date

from app.paper.broker import cash_balance, validate_paper_ledger
from app.policy.decision_policy import PortfolioContext


def position_tickers(conn: sqlite3.Connection) -> list[str]:
    validate_paper_ledger(conn)
    return [row[0] for row in conn.execute("SELECT ticker FROM paper_positions ORDER BY ticker")]


def _latest_close(conn: sqlite3.Connection, ticker: str, on_date: date) -> float:
    row = conn.execute(
        """
        SELECT close FROM daily_prices WHERE ticker = ? AND bar_date <= ?
        ORDER BY bar_date DESC LIMIT 1
        """,
        (ticker, on_date.isoformat()),
    ).fetchone()
    if row is None:
        raise ValueError(f"missing cached close for {ticker} on or before {on_date}")
    return float(row[0])


def portfolio_context(
    conn: sqlite3.Connection, on_date: date, exclude_ticker: str | None = None
) -> PortfolioContext:
    positions = conn.execute(
        "SELECT ticker, shares, primary_theme_id FROM paper_positions"
    ).fetchall()
    values = {
        ticker: shares * _latest_close(conn, ticker, on_date) for ticker, shares, _ in positions
    }
    equity = cash_balance(conn, on_date) + sum(values.values())
    theme_weights: dict[str, float] = {}
    for ticker, _, theme in positions:
        if ticker != exclude_ticker and theme:
            theme_weights[theme] = theme_weights.get(theme, 0.0) + values[ticker] / equity
    counts = dict(
        conn.execute(
            """
            SELECT side, COUNT(*) FROM order_intents
            WHERE substr(created_at, 1, 10) = ? AND execution_mode = 'PAPER' GROUP BY side
            """,
            (on_date.isoformat(),),
        ).fetchall()
    )
    return PortfolioContext(
        holdings_count=len(positions),
        buy_add_trades_today=counts.get("BUY", 0),
        sell_trim_trades_today=counts.get("SELL", 0),
        primary_theme_weights=theme_weights,
    )
