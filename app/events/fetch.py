from collections.abc import Callable
from datetime import date
from typing import Any

import yfinance

FOMC_COVERAGE_END = date(2026, 12, 31)
FOMC_MEETING_DATES = (
    date(2026, 1, 27),
    date(2026, 1, 28),
    date(2026, 3, 17),
    date(2026, 3, 18),
    date(2026, 4, 28),
    date(2026, 4, 29),
    date(2026, 6, 16),
    date(2026, 6, 17),
    date(2026, 7, 28),
    date(2026, 7, 29),
    date(2026, 9, 15),
    date(2026, 9, 16),
    date(2026, 10, 27),
    date(2026, 10, 28),
    date(2026, 12, 8),
    date(2026, 12, 9),
)


class FomcCoverageError(ValueError):
    pass


def fomc_dates(through: date) -> tuple[date, ...]:
    if through > FOMC_COVERAGE_END:
        raise FomcCoverageError(f"FOMC calendar coverage ends at {FOMC_COVERAGE_END}")
    return tuple(meeting_date for meeting_date in FOMC_MEETING_DATES if meeting_date <= through)


def _yfinance_earnings(ticker: str) -> Any:
    return yfinance.Ticker(ticker).get_earnings_dates(limit=12)


def fetch_earnings_dates(
    ticker: str,
    fetcher: Callable[[str], Any] = _yfinance_earnings,
    today: date | None = None,
) -> list[date]:
    today = today or date.today()
    earnings = fetcher(ticker)
    if earnings is None:
        return []
    return sorted({index.date() for index in earnings.index if index.date() >= today})
