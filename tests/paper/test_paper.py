import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from app.paper.broker import rebuild_positions, settle
from app.paper.context import portfolio_context
from app.prices.cache import PriceBar, upsert_daily_prices
from app.schemas.order_intent import OrderIntent
from app.storage.database import connect
from app.storage.records import save_decision_record, save_order_intent
from tests.fixtures.decision_records import decision_record_with


def _bar(ticker: str, bar_date: date, open_price: float, close: float | None = None) -> PriceBar:
    close = close if close is not None else open_price
    return PriceBar(
        ticker=ticker,
        bar_date=bar_date,
        open=open_price,
        high=max(open_price, close),
        low=min(open_price, close),
        close=close,
        adj_close=close,
        volume=100,
        source="test",
        fetched_at=datetime(2026, 7, 1, tzinfo=UTC),
    )


def _intent(
    conn: sqlite3.Connection,
    identifier: str,
    side: str,
    target_weight: float,
    created: date,
    ticker: str = "NVDA",
    theme: str = "ai_semiconductors",
) -> OrderIntent:
    record = decision_record_with(
        decision_id=f"dec_{identifier}",
        ticker=ticker,
        decision="BUY" if side == "BUY" else "SELL",
        final_target_weight=target_weight,
        proposed_target_weight=target_weight,
        primary_theme_id=theme,
        created_at=datetime.combine(created, datetime.min.time(), tzinfo=UTC),
    )
    intent = OrderIntent(
        order_intent_id=f"oi_{identifier}",
        decision_id=record.decision_id,
        created_at=record.created_at,
        ticker=ticker,
        side=side,
        order_type="MARKET",
        target_weight=target_weight,
    )
    save_decision_record(conn, record)
    save_order_intent(conn, intent)
    return intent


def test_settle_uses_earliest_bar_after_intent_and_replay_matches(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    _intent(conn, "buy", "BUY", 0.10, date(2026, 7, 20))
    upsert_daily_prices(
        conn,
        [_bar("NVDA", date(2026, 7, 20), 90), _bar("NVDA", date(2026, 7, 21), 100)],
    )

    assert settle(conn) == (1, 0)
    incremental = conn.execute("SELECT * FROM paper_positions").fetchall()
    fill = conn.execute("SELECT price, fill_date FROM paper_fills").fetchone()
    rebuild_positions(conn)

    assert fill == (100.0, "2026-07-21")
    assert conn.execute("SELECT * FROM paper_positions").fetchall() == incremental
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO paper_fills
                (fill_id, order_intent_id, ticker, side, shares, price, fill_date, filled_at)
            VALUES ('duplicate', 'oi_buy', 'NVDA', 'BUY', 1, 1, '2026-07-21', 'now')
            """
        )


def test_settle_awaits_missing_bar(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    _intent(conn, "buy", "BUY", 0.10, date(2026, 7, 20))

    assert settle(conn) == (0, 1)


def test_settle_rejects_stale_sign_mismatch(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    _intent(conn, "sell", "SELL", 0.10, date(2026, 7, 20))
    upsert_daily_prices(conn, [_bar("NVDA", date(2026, 7, 21), 100)])

    with pytest.raises(ValueError, match="non-negative delta"):
        settle(conn)


def test_buy_average_cost_sell_cap_and_close_delete(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    _intent(conn, "buy1", "BUY", 0.10, date(2026, 7, 19))
    upsert_daily_prices(conn, [_bar("NVDA", date(2026, 7, 20), 100)])
    settle(conn)
    _intent(conn, "buy2", "BUY", 0.20, date(2026, 7, 20))
    upsert_daily_prices(conn, [_bar("NVDA", date(2026, 7, 21), 200)])
    settle(conn)

    shares, avg_cost = conn.execute(
        "SELECT shares, avg_cost FROM paper_positions WHERE ticker = 'NVDA'"
    ).fetchone()
    assert shares > 5
    assert 100 < avg_cost < 200

    _intent(conn, "sell", "SELL", 0.0, date(2026, 7, 21))
    upsert_daily_prices(conn, [_bar("NVDA", date(2026, 7, 22), 150)])
    settle(conn)
    assert conn.execute("SELECT COUNT(*) FROM paper_positions").fetchone()[0] == 0
    sold = conn.execute(
        "SELECT shares FROM paper_fills WHERE order_intent_id = 'oi_sell'"
    ).fetchone()[0]
    assert sold == pytest.approx(shares)


def test_fill_equity_uses_fill_date_closes_for_other_holdings(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    _intent(conn, "amd", "BUY", 0.10, date(2026, 7, 19), ticker="AMD")
    upsert_daily_prices(conn, [_bar("AMD", date(2026, 7, 20), 100)])
    settle(conn)
    _intent(conn, "nvda", "BUY", 0.10, date(2026, 7, 20))
    upsert_daily_prices(
        conn,
        [
            _bar("AMD", date(2026, 7, 21), 100, close=200),
            _bar("NVDA", date(2026, 7, 21), 100),
        ],
    )

    settle(conn)

    nvda_shares = conn.execute(
        "SELECT shares FROM paper_positions WHERE ticker = 'NVDA'"
    ).fetchone()[0]
    assert nvda_shares == pytest.approx(5.5)


def test_portfolio_context_counts_intents_and_excludes_ticker(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    _intent(conn, "nvda", "BUY", 0.10, date(2026, 7, 19))
    _intent(conn, "amd", "BUY", 0.10, date(2026, 7, 19), ticker="AMD")
    _intent(conn, "old", "SELL", 0.0, date(2026, 7, 19), ticker="OLD")
    upsert_daily_prices(
        conn,
        [_bar("NVDA", date(2026, 7, 20), 100), _bar("AMD", date(2026, 7, 20), 100)],
    )
    settle(conn)
    upsert_daily_prices(
        conn,
        [_bar("NVDA", date(2026, 7, 21), 100), _bar("AMD", date(2026, 7, 21), 100)],
    )
    _intent(conn, "count1", "BUY", 0.15, date(2026, 7, 21), ticker="MSFT")
    _intent(conn, "count2", "BUY", 0.15, date(2026, 7, 21), ticker="GOOG")

    context = portfolio_context(conn, date(2026, 7, 21), exclude_ticker="NVDA")

    assert context.holdings_count == 2
    assert context.buy_add_trades_today == 2
    assert context.sell_trim_trades_today == 0
    assert sum(context.primary_theme_weights.values()) < 1
