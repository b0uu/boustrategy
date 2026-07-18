from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from app.prices.cache import PriceBar, upsert_daily_prices
from app.storage.database import connect
from app.triggers.evaluate import evaluate_triggers
from app.triggers.store import insert_trigger, mark_triggers, trigger_id
from app.x.posts import XPost, insert_new_posts


def _bars(count: int, final_close: float = 100.0, final_volume: int = 100) -> list[PriceBar]:
    start = date(2026, 6, 22)
    bars = []
    for index in range(count):
        bar_date = start + timedelta(days=index)
        close = final_close if index == count - 1 else 100.0
        volume = final_volume if index == count - 1 else 100
        bars.append(
            PriceBar(
                ticker="NVDA",
                bar_date=bar_date,
                open=close,
                high=close,
                low=close,
                close=close,
                adj_close=close,
                volume=volume,
                source="test",
                fetched_at=datetime(2026, 7, 1, tzinfo=UTC),
            )
        )
    return bars


def test_price_threshold_boundary_fires_idempotently(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    bars = _bars(2, final_close=105.0)
    upsert_daily_prices(conn, bars)
    evaluation_date = bars[-1].bar_date

    first = evaluate_triggers(conn, ["NVDA"], evaluation_date)
    second = evaluate_triggers(conn, ["NVDA"], evaluation_date)

    assert first["price_move"] == 1
    assert second["price_move"] == 0
    assert conn.execute("SELECT COUNT(*) FROM trigger_events").fetchone()[0] == 1


def test_consumed_trigger_is_not_resurrected(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    bars = _bars(2, final_close=105.0)
    upsert_daily_prices(conn, bars)
    evaluation_date = bars[-1].bar_date
    evaluate_triggers(conn, ["NVDA"], evaluation_date)
    item = trigger_id("price_move", "NVDA", evaluation_date)
    mark_triggers(conn, [item], "consumed")

    evaluate_triggers(conn, ["NVDA"], evaluation_date)

    assert (
        conn.execute("SELECT status FROM trigger_events WHERE trigger_id = ?", (item,)).fetchone()[
            0
        ]
        == "consumed"
    )


def test_volume_requires_twenty_prior_bars(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    bars = _bars(20, final_volume=300)
    upsert_daily_prices(conn, bars)

    counts = evaluate_triggers(conn, ["NVDA"], bars[-1].bar_date)

    assert counts["volume_spike"] == 0


def test_volume_boundary_fires_with_twenty_prior_bars(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    bars = _bars(21, final_volume=300)
    upsert_daily_prices(conn, bars)

    counts = evaluate_triggers(conn, ["NVDA"], bars[-1].bar_date)

    assert counts["volume_spike"] == 1


def test_missing_prior_bar_skips_price_move(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    bars = _bars(1, final_close=110)
    upsert_daily_prices(conn, bars)

    counts = evaluate_triggers(conn, ["NVDA"], bars[-1].bar_date)

    assert counts["price_move"] == 0


def test_calendar_window_fires_once_across_evaluations(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    conn.execute(
        """
        INSERT INTO calendar_events
            (event_type, ticker, event_date, label, source, fetched_at)
        VALUES ('earnings', 'NVDA', '2026-07-22', 'estimated', 'test', '2026-07-01')
        """
    )

    first = evaluate_triggers(conn, [], date(2026, 7, 20))
    second = evaluate_triggers(conn, [], date(2026, 7, 21))

    assert first["calendar_upcoming"] == 1
    assert second["calendar_upcoming"] == 0


def test_only_headline_routes_fire_digest_trigger(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    now = datetime(2026, 7, 20, 12, tzinfo=UTC)
    insert_new_posts(
        conn,
        [
            XPost(post_id="1", handle="a", posted_at=now, text="one", url="u1", fetched_at=now),
            XPost(post_id="2", handle="a", posted_at=now, text="two", url="u2", fetched_at=now),
        ],
    )
    conn.executemany(
        """
        INSERT INTO x_route_decisions
            (post_id, run_id, route, rank, reason, predictor, decided_at)
        VALUES (?, 'run', 'digest', ?, 'reason', 'judge', ?)
        """,
        [("1", "headline", now.isoformat()), ("2", "notable", now.isoformat())],
    )
    conn.commit()

    counts = evaluate_triggers(conn, [], date(2026, 7, 20))

    assert counts["digest_headline"] == 1
    assert conn.execute(
        "SELECT subject FROM trigger_events WHERE trigger_type = 'digest_headline'"
    ).fetchall() == [("1",)]


def test_expiry_boundary_and_mark_validation(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    evaluation_date = date(2026, 7, 20)
    old = date(2026, 7, 14)
    boundary = date(2026, 7, 15)
    insert_trigger(conn, "price_move", "OLD", old, old, {})
    insert_trigger(conn, "price_move", "BOUNDARY", boundary, boundary, {})

    counts = evaluate_triggers(conn, [], evaluation_date)

    assert counts["expired"] == 1
    assert (
        conn.execute("SELECT status FROM trigger_events WHERE subject = 'BOUNDARY'").fetchone()[0]
        == "pending"
    )
    item = trigger_id("price_move", "BOUNDARY", boundary)
    with pytest.raises(ValueError, match="invalid target"):
        mark_triggers(conn, [item], "pending")
    mark_triggers(conn, [item], "consumed")
    with pytest.raises(ValueError, match="cannot transition"):
        mark_triggers(conn, [item], "expired")
