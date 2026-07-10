import sqlite3
from collections.abc import Callable
from datetime import date

from pydantic import AwareDatetime, BaseModel, ConfigDict


class PriceBar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    bar_date: date
    open: float
    high: float
    low: float
    close: float
    adj_close: float | None
    volume: int
    source: str
    fetched_at: AwareDatetime


def upsert_daily_prices(conn: sqlite3.Connection, bars: list[PriceBar]) -> int:
    conn.executemany(
        """
        INSERT OR REPLACE INTO daily_prices
            (ticker, bar_date, open, high, low, close, adj_close, volume, source, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                bar.ticker,
                bar.bar_date.isoformat(),
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.adj_close,
                bar.volume,
                bar.source,
                bar.fetched_at.isoformat(),
            )
            for bar in bars
        ],
    )
    conn.commit()
    return len(bars)


def get_daily_prices(
    conn: sqlite3.Connection,
    ticker: str,
    start: date | None = None,
    end: date | None = None,
) -> list[PriceBar]:
    query = """
        SELECT ticker, bar_date, open, high, low, close, adj_close, volume, source, fetched_at
        FROM daily_prices
        WHERE ticker = ?
    """
    parameters: list[str] = [ticker]
    if start is not None:
        query += " AND bar_date >= ?"
        parameters.append(start.isoformat())
    if end is not None:
        query += " AND bar_date <= ?"
        parameters.append(end.isoformat())
    query += " ORDER BY bar_date ASC"

    rows = conn.execute(query, parameters).fetchall()
    return [
        PriceBar(
            ticker=row[0],
            bar_date=row[1],
            open=row[2],
            high=row[3],
            low=row[4],
            close=row[5],
            adj_close=row[6],
            volume=row[7],
            source=row[8],
            fetched_at=row[9],
        )
        for row in rows
    ]


def latest_bar_date(conn: sqlite3.Connection, ticker: str) -> date | None:
    row = conn.execute(
        "SELECT MAX(bar_date) FROM daily_prices WHERE ticker = ?",
        (ticker,),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return date.fromisoformat(row[0])


def refresh_ticker(
    conn: sqlite3.Connection,
    ticker: str,
    start: date,
    end: date,
    fetch: Callable[[str, date, date], list[PriceBar]] | None = None,
) -> int:
    if fetch is None:
        from app.prices.yfinance_source import fetch_daily_bars

        fetch = fetch_daily_bars
    return upsert_daily_prices(conn, fetch(ticker, start, end))
