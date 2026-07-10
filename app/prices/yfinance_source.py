import math
from datetime import UTC, date, datetime

import yfinance

from app.prices.cache import PriceBar


def fetch_daily_bars(ticker: str, start: date, end: date) -> list[PriceBar]:
    history = yfinance.Ticker(ticker).history(
        start=start,
        end=end,
        interval="1d",
        auto_adjust=False,
    )
    fetched_at = datetime.now(UTC)
    bars: list[PriceBar] = []
    for index, row in history.iterrows():
        close = float(row["Close"])
        if math.isnan(close):
            continue
        adj_close_value = row.get("Adj Close")
        adj_close = (
            None
            if adj_close_value is None or math.isnan(float(adj_close_value))
            else float(adj_close_value)
        )
        bars.append(
            PriceBar(
                ticker=ticker,
                bar_date=index.date(),
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=close,
                adj_close=adj_close,
                volume=int(row["Volume"]),
                source="yfinance",
                fetched_at=fetched_at,
            )
        )
    return bars
