from datetime import UTC, date, datetime, timedelta

from app.prices.cache import (
    PriceBar,
    get_daily_prices,
    latest_bar_date,
    refresh_ticker,
    upsert_daily_prices,
)
from app.storage.database import connect


def price_bar(
    ticker: str = "QQQ",
    bar_date: date = date(2026, 6, 1),
    close: float = 100.0,
) -> PriceBar:
    return PriceBar(
        ticker=ticker,
        bar_date=bar_date,
        open=close - 1.0,
        high=close + 1.0,
        low=close - 2.0,
        close=close,
        adj_close=close,
        volume=1_000_000,
        source="test",
        fetched_at=datetime(2026, 6, 2, 0, 0, tzinfo=UTC),
    )


def test_upsert_and_get_round_trip():
    conn = connect(":memory:")
    bars = [
        price_bar(bar_date=date(2026, 6, 3), close=103.0),
        price_bar(bar_date=date(2026, 6, 1), close=101.0),
        price_bar(bar_date=date(2026, 6, 2), close=102.0),
    ]

    written = upsert_daily_prices(conn, bars)
    loaded = get_daily_prices(conn, "QQQ")

    assert written == 3
    assert loaded == sorted(bars, key=lambda bar: bar.bar_date)


def test_upsert_same_day_replaces():
    conn = connect(":memory:")
    original = price_bar(close=100.0)
    replacement = price_bar(close=110.0)

    upsert_daily_prices(conn, [original])
    upsert_daily_prices(conn, [replacement])
    loaded = get_daily_prices(conn, "QQQ")

    assert len(loaded) == 1
    assert loaded[0].close == 110.0


def test_get_with_date_range_filters():
    conn = connect(":memory:")
    first_date = date(2026, 6, 1)
    bars = [price_bar(bar_date=first_date + timedelta(days=offset)) for offset in range(5)]
    upsert_daily_prices(conn, bars)

    loaded = get_daily_prices(
        conn,
        "QQQ",
        start=date(2026, 6, 2),
        end=date(2026, 6, 4),
    )

    assert [bar.bar_date for bar in loaded] == [
        date(2026, 6, 2),
        date(2026, 6, 3),
        date(2026, 6, 4),
    ]


def test_latest_bar_date():
    conn = connect(":memory:")
    bars = [
        price_bar(bar_date=date(2026, 6, 1)),
        price_bar(bar_date=date(2026, 6, 3)),
    ]
    upsert_daily_prices(conn, bars)

    latest = latest_bar_date(conn, "QQQ")
    missing = latest_bar_date(conn, "SPY")

    assert latest == date(2026, 6, 3)
    assert missing is None


def test_refresh_ticker_uses_injected_fetcher():
    conn = connect(":memory:")
    start = date(2026, 6, 1)
    end = date(2026, 6, 30)
    expected = [price_bar(bar_date=start), price_bar(bar_date=date(2026, 6, 2))]

    def fake_fetch(ticker: str, fetch_start: date, fetch_end: date) -> list[PriceBar]:
        assert ticker == "QQQ"
        assert fetch_start == start
        assert fetch_end == end
        return expected

    written = refresh_ticker(conn, "QQQ", start, end, fetch=fake_fetch)

    assert written == 2
    assert get_daily_prices(conn, "QQQ") == expected


def test_bars_for_different_tickers_do_not_collide():
    conn = connect(":memory:")
    qqq = price_bar(ticker="QQQ")
    spy = price_bar(ticker="SPY", close=200.0)

    upsert_daily_prices(conn, [qqq, spy])

    assert get_daily_prices(conn, "QQQ") == [qqq]
    assert get_daily_prices(conn, "SPY") == [spy]
