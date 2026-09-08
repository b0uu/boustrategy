import sqlite3
from datetime import UTC, date, datetime, time
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
    created_at: datetime | None = None,
) -> OrderIntent:
    record = decision_record_with(
        decision_id=f"dec_{identifier}",
        ticker=ticker,
        decision="BUY" if side == "BUY" else "SELL",
        final_target_weight=target_weight,
        proposed_target_weight=target_weight,
        primary_theme_id=theme,
        created_at=created_at or datetime.combine(created, time(12, 0), tzinfo=UTC),
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


def test_evening_et_intent_fills_at_next_session_open_not_the_one_after(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    _intent(
        conn,
        "buy",
        "BUY",
        0.10,
        date(2026, 7, 20),
        created_at=datetime(2026, 7, 21, 1, 30, tzinfo=UTC),
    )
    upsert_daily_prices(
        conn,
        [
            _bar("NVDA", date(2026, 7, 20), 90),
            _bar("NVDA", date(2026, 7, 21), 100),
            _bar("NVDA", date(2026, 7, 22), 110),
        ],
    )

    assert settle(conn) == (1, 0)

    assert conn.execute("SELECT price, fill_date FROM paper_fills").fetchone() == (
        100.0,
        "2026-07-21",
    )


def test_settle_awaits_missing_bar(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    _intent(conn, "buy", "BUY", 0.10, date(2026, 7, 20))

    assert settle(conn) == (0, 1)


def test_settle_does_not_use_bars_after_requested_date(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    _intent(conn, "buy", "BUY", 0.10, date(2026, 7, 20))
    upsert_daily_prices(conn, [_bar("NVDA", date(2026, 7, 21), 100)])

    assert settle(conn, through_date=date(2026, 7, 20)) == (0, 1)
    assert settle(conn, through_date=date(2026, 7, 21)) == (1, 0)


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


def test_fill_equity_uses_contemporaneous_opens_for_other_holdings(tmp_path: Path) -> None:
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
    assert nvda_shares == pytest.approx(5.0)


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


def test_live_intents_never_settle_into_paper_or_consume_paper_quota(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    intent = _intent(conn, "live", "BUY", 0.1, date(2026, 7, 20))
    live = OrderIntent.model_validate(
        {**intent.model_dump(), "execution_mode": "LIVE", "execution_profile_id": "live_profile"}
    )
    conn.execute(
        "UPDATE order_intents SET execution_mode='LIVE', execution_profile_id='live_profile', "
        "intent_json=? WHERE order_intent_id=?",
        (live.model_dump_json(), intent.order_intent_id),
    )
    conn.commit()
    upsert_daily_prices(conn, [_bar("NVDA", date(2026, 7, 21), 100)])

    assert settle(conn) == (0, 0)
    assert portfolio_context(conn, date(2026, 7, 20)).buy_add_trades_today == 0
    assert conn.execute("SELECT COUNT(*) FROM paper_fills").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM paper_positions").fetchone()[0] == 0


def test_reporting_reconstructs_paper_without_changing_fill_economics(tmp_path: Path) -> None:
    from app.performance.paper import paper_observations
    from app.performance.report import materialize

    conn = connect(tmp_path / "synthetic.db")
    _intent(conn, "buy", "BUY", 0.10, date(2026, 7, 20))
    upsert_daily_prices(conn, [_bar("NVDA", date(2026, 7, 21), 100, 110)])
    assert settle(conn) == (1, 0)
    before = conn.execute("SELECT shares, price FROM paper_fills").fetchone()
    observations, issue = paper_observations(conn)
    overview, ranges = materialize(conn, observations)
    assert issue is None
    assert overview["equity"] == "5050.00"
    assert ranges["All"]["return_percent"] == "1.000000"
    assert overview["recent_fills"][0]["fee"] == "0"
    assert conn.execute("SELECT shares, price FROM paper_fills").fetchone() == before


def test_contaminated_paper_fills_and_mismatched_positions_are_quarantined(tmp_path: Path) -> None:
    from app.performance.paper import paper_observations

    conn = connect(tmp_path / "synthetic.db")
    _intent(conn, "buy", "BUY", 0.10, date(2026, 7, 20))
    upsert_daily_prices(conn, [_bar("NVDA", date(2026, 7, 21), 100)])
    settle(conn)
    conn.execute("UPDATE paper_positions SET shares=999")
    assert paper_observations(conn)[1] == "paper_positions_do_not_reconcile"
    conn.execute("UPDATE order_intents SET execution_mode='LIVE', execution_profile_id='live'")
    assert paper_observations(conn) == ([], "paper_ledger_contains_unscoped_or_live_fills")
    assert conn.execute("SELECT shares FROM paper_positions").fetchone()[0] == 999


def test_unaffordable_buy_rolls_back_entire_settlement(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    _intent(conn, "first", "BUY", 0.8, date(2026, 7, 20))
    _intent(conn, "second", "BUY", 0.8, date(2026, 7, 20), ticker="AMD")
    upsert_daily_prices(
        conn, [_bar("NVDA", date(2026, 7, 21), 100), _bar("AMD", date(2026, 7, 21), 100)]
    )
    with pytest.raises(ValueError, match="insufficient_cash"):
        settle(conn)
    assert conn.execute("SELECT COUNT(*) FROM paper_fills").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM paper_positions").fetchone()[0] == 0
    conn.close()


def test_missing_holding_open_waits_without_using_future_close(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    _intent(conn, "first", "BUY", 0.1, date(2026, 7, 20))
    upsert_daily_prices(conn, [_bar("NVDA", date(2026, 7, 21), 100)])
    settle(conn)
    _intent(conn, "second", "BUY", 0.1, date(2026, 7, 21), ticker="AMD")
    upsert_daily_prices(conn, [_bar("AMD", date(2026, 7, 22), 100)])
    assert settle(conn) == (0, 1)
    assert (
        conn.execute("SELECT simulation_version FROM paper_fills").fetchone()[0] == "next_open_v2"
    )
    conn.close()


def test_rebuild_failure_preserves_previous_positions(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    _intent(conn, "buy", "BUY", 0.1, date(2026, 7, 20))
    upsert_daily_prices(conn, [_bar("NVDA", date(2026, 7, 21), 100)])
    settle(conn)
    before = conn.execute("SELECT * FROM paper_positions").fetchall()
    conn.execute(
        "CREATE TRIGGER reject_rebuild BEFORE INSERT ON paper_positions "
        "BEGIN SELECT RAISE(ABORT, 'synthetic rebuild failure'); END"
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="synthetic rebuild"):
        rebuild_positions(conn)
    assert conn.execute("SELECT * FROM paper_positions").fetchall() == before
    assert not conn.in_transaction
    conn.close()


def test_contaminated_fills_block_all_paper_operations(tmp_path: Path) -> None:
    from app.paper.broker import cash_balance

    conn = connect(tmp_path / "synthetic.db")
    _intent(conn, "buy", "BUY", 0.1, date(2026, 7, 20))
    upsert_daily_prices(conn, [_bar("NVDA", date(2026, 7, 21), 100)])
    settle(conn)
    conn.execute("UPDATE order_intents SET execution_mode='LIVE', execution_profile_id='live'")
    conn.commit()
    for operation in (cash_balance, settle, rebuild_positions):
        with pytest.raises(ValueError, match="unscoped_or_live_fills"):
            operation(conn)
    assert conn.execute("SELECT COUNT(*) FROM paper_fills").fetchone()[0] == 1
    conn.close()
