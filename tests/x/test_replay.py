import json
import sqlite3
from datetime import UTC, date, datetime

from app.prices.cache import PriceBar, upsert_daily_prices
from app.storage.database import connect
from app.x.replay import evaluate_candidates, extract_cashtags, load_candidates, render_report


def _bar(ticker: str, day: date, open_price: float, close: float) -> PriceBar:
    return PriceBar(
        ticker=ticker,
        bar_date=day,
        open=open_price,
        high=max(open_price, close),
        low=min(open_price, close),
        close=close,
        adj_close=close,
        volume=100,
        source="test",
        fetched_at=datetime(2026, 7, 30, tzinfo=UTC),
    )


def _route(
    conn: sqlite3.Connection,
    decided_at: str,
    text: str = "Watching $NVDA and $NVDA, not USD",
) -> None:
    conn.execute(
        """
        INSERT INTO x_posts
            (post_id, handle, posted_at, text, url, fetched_at, review_status)
        VALUES ('1', 'analyst', '2026-07-20T12:00:00+00:00', ?, 'https://x/1',
                '2026-07-20T12:05:00+00:00', 'significant')
        """,
        (text,),
    )
    conn.execute(
        """
        INSERT INTO x_runs (run_id, slot, started_at, status)
        VALUES ('run', 'morning', '2026-07-20T12:00:00+00:00', 'routed')
        """
    )
    conn.execute(
        """
        INSERT INTO x_route_decisions
            (post_id, run_id, route, rank, reason, predictor, decided_at)
        VALUES ('1', 'run', 'digest', 'headline', 'reason', 'judge', ?)
        """,
        (decided_at,),
    )
    conn.commit()


def test_extract_cashtags_is_deterministic_and_requires_dollar_prefix() -> None:
    assert extract_cashtags("$nvda NVDA $QQQ $NVDA $TOOLONG") == ("NVDA", "QQQ")


def test_candidates_use_latest_availability_and_ignore_unclocked_review_label() -> None:
    conn = connect(":memory:")
    _route(conn, "2026-07-20T12:10:00+00:00")

    candidates = load_candidates(conn, datetime(2026, 7, 21, tzinfo=UTC))

    assert len(candidates) == 1
    assert candidates[0].available_at == datetime(2026, 7, 20, 12, 10, tzinfo=UTC)
    assert candidates[0].tickers == ("NVDA",)


def test_evaluation_moves_post_open_decision_to_next_session() -> None:
    conn = connect(":memory:")
    _route(conn, "2026-07-20T14:00:00+00:00")
    upsert_daily_prices(
        conn,
        [
            _bar("NVDA", date(2026, 7, 20), 90, 95),
            _bar("NVDA", date(2026, 7, 21), 100, 110),
            _bar("QQQ", date(2026, 7, 20), 400, 404),
            _bar("QQQ", date(2026, 7, 21), 410, 414.1),
        ],
    )
    evaluated_at = datetime(2026, 7, 22, tzinfo=UTC)

    results, missing = evaluate_candidates(
        conn, load_candidates(conn, evaluated_at), evaluated_at, horizons=(1,)
    )

    assert missing == []
    assert len(results) == 1
    assert results[0].entry_date == "2026-07-21"
    assert results[0].return_pct == 10.0
    assert results[0].benchmark_return_pct == 1.0
    assert results[0].excess_return_pct == 9.0


def test_report_discloses_missing_prices_and_excluded_labels() -> None:
    conn = connect(":memory:")
    _route(conn, "2026-07-20T12:10:00+00:00")
    upsert_daily_prices(conn, [_bar("QQQ", date(2026, 7, 21), 400, 404)])

    report, payload = render_report(conn, datetime(2026, 7, 22, tzinfo=UTC), horizons=(1,))

    assert "1 human review labels are excluded" in report
    assert "Missing price series: NVDA" in report
    assert payload["excluded_untimestamped_human_labels"] == 1
    assert json.dumps(payload, default=str)


def test_missing_first_session_bar_does_not_shift_replay_entry() -> None:
    conn = connect(":memory:")
    _route(conn, "2026-07-20T12:10:00+00:00")
    upsert_daily_prices(
        conn, [_bar("NVDA", date(2026, 7, 21), 100, 110), _bar("QQQ", date(2026, 7, 21), 400, 410)]
    )
    at = datetime(2026, 7, 22, tzinfo=UTC)
    results, missing = evaluate_candidates(conn, load_candidates(conn, at), at, horizons=(1,))
    assert results == []
    assert missing == ["NVDA"]
    conn.close()
