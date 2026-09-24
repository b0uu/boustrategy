import json
import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from app.broker.collector import collect_snapshot
from app.schemas.live_execution import LivePortfolioSnapshot
from app.schemas.public_authoring import ThesisReview
from app.storage.database import connect
from app.storage.holding_reviews import (
    holdings_due,
    latest_review_point,
    live_holding_episodes,
    thesis_prices,
)
from app.storage.public_records import save_thesis_review
from app.triggers.store import insert_trigger
from tests.reason.test_live_submit import _profile

ACCOUNT = "0" * 16
# Monday 2026-09-21, 10:00 ET.
MONDAY_MORNING = datetime(2026, 9, 21, 14, 0, tzinfo=UTC)


def snapshot_at(
    conn: sqlite3.Connection,
    folder: Path,
    at: datetime,
    holdings: dict[str, tuple[float, float, float]],
    equity: float = 100.0,
    qqq: float | None = None,
) -> LivePortfolioSnapshot:
    """Collect a live snapshot whose holdings map ticker to (quantity, average_cost, price)."""
    invested = sum(round(quantity * price, 2) for quantity, _, price in holdings.values())

    def session(prompt: str, *, schema: Any, **kwargs: Any) -> Any:
        return schema.model_validate(
            {
                "broker_account_fingerprint": ACCOUNT,
                "account_equity": equity,
                "buying_power": round(equity - invested, 2),
                "cash": round(equity - invested, 2),
                "positions": [
                    {
                        "ticker": ticker,
                        "market_value": round(quantity * price, 2),
                        "quantity": quantity,
                        "average_cost": cost,
                        "price": price,
                        "quote_at": at.isoformat(),
                    }
                    for ticker, (quantity, cost, price) in holdings.items()
                ],
                "qqq_price": qqq,
            }
        )

    return collect_snapshot(conn, _profile(), session=session, now=at, codex_home=folder)


def review(
    conn: sqlite3.Connection,
    episode_id: str,
    ticker: str,
    at: datetime,
    *,
    state: Literal["intact", "invalidated"] = "intact",
    reasons: list[str] | None = None,
    # Far enough off that no test price reaches either end, so the holding has a stated range.
    prices: tuple[float, float, float] = (10_000.0, 20_000.0, 0.01),
) -> None:
    save_thesis_review(
        conn,
        ThesisReview(
            review_id="review_" + at.isoformat(),
            mode="live",
            account_id=ACCOUNT,
            episode_id=episode_id,
            ticker=ticker,
            reviewed_at=at,
            recorded_at=at,
            author="operator",
            state=state,
            summary="Still holds.",
            review_reasons=reasons or [],
            realization_price_low=prices[0],
            realization_price_high=prices[1],
            invalidation_price=prices[2],
        ),
    )


def x_post(
    conn: sqlite3.Connection,
    post_id: str,
    text: str,
    rank: str,
    tickers: list[str],
    decided_at: datetime = datetime(2026, 9, 22, 13, 0, tzinfo=UTC),
) -> None:
    conn.execute(
        "INSERT INTO x_posts (post_id, handle, posted_at, text, url, fetched_at) "
        "VALUES (?, 'analyst', '2026-09-22T12:00:00+00:00', ?, ?, '2026-09-22T12:05:00+00:00')",
        (post_id, text, f"https://x.com/analyst/status/{post_id}"),
    )
    conn.execute(
        "INSERT INTO x_route_decisions "
        "(post_id, run_id, route, rank, reason, predictor, decided_at, tickers) "
        "VALUES (?, 'run', 'digest', ?, '', 'predictor', ?, ?)",
        (post_id, rank, decided_at.isoformat(), json.dumps(tickers)),
    )


def test_an_episode_opens_when_a_holding_first_appears_and_restarts_after_a_sale(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    first = MONDAY_MORNING
    snapshot_at(conn, tmp_path, first, {"NVDA": (0.1, 200, 200)})
    snapshot_at(
        conn, tmp_path, first + timedelta(hours=1), {"NVDA": (0.1, 200, 200), "MU": (1, 10, 10)}
    )
    snapshot_at(conn, tmp_path, first + timedelta(hours=2), {"MU": (1, 10, 10)})
    reopened = first + timedelta(hours=3)
    snapshot_at(conn, tmp_path, reopened, {"NVDA": (0.1, 200, 200), "MU": (1, 10, 10)})

    episodes = live_holding_episodes(conn, ACCOUNT, reopened)

    assert episodes["MU"]["opened_at"] == (first + timedelta(hours=1)).isoformat()
    assert episodes["NVDA"]["opened_at"] == reopened.isoformat()
    assert episodes["NVDA"]["episode_id"] == f"live:{ACCOUNT}:NVDA:{reopened.isoformat()}"
    assert live_holding_episodes(conn, "f" * 16, reopened) == {}
    conn.close()


def test_review_points_are_monday_wednesday_and_friday_at_noon() -> None:
    wednesday_midday = datetime(2026, 9, 23, 17, 0, tzinfo=UTC)
    wednesday_morning = datetime(2026, 9, 23, 14, 0, tzinfo=UTC)
    sunday = datetime(2026, 9, 27, 16, 0, tzinfo=UTC)

    points = [
        latest_review_point(moment) for moment in (wednesday_midday, wednesday_morning, sunday)
    ]

    assert [point.isoformat() for point in points] == [
        "2026-09-23T12:00:00-04:00",
        "2026-09-21T12:00:00-04:00",
        "2026-09-25T12:00:00-04:00",
    ]


def test_a_significant_holding_is_due_until_reviewed_after_the_latest_point(tmp_path: Path) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    snapshot = snapshot_at(conn, tmp_path, MONDAY_MORNING, {"NVDA": (0.1, 200, 200)})
    episode = live_holding_episodes(conn, ACCOUNT, MONDAY_MORNING)["NVDA"]["episode_id"]
    tuesday_morning = MONDAY_MORNING + timedelta(days=1)
    wednesday_midday = MONDAY_MORNING + timedelta(days=2, hours=3)

    never_reviewed = holdings_due(conn, snapshot, MONDAY_MORNING)
    review(conn, episode, "NVDA", MONDAY_MORNING + timedelta(minutes=20))
    reviewed_this_point = holdings_due(conn, snapshot, tuesday_morning)
    next_point = holdings_due(conn, snapshot, wednesday_midday)

    assert [item["reasons"] for item in never_reviewed] == [["scheduled_review", "range_missing"]]
    assert reviewed_this_point == []
    assert next_point[0]["episode_id"] == episode
    assert next_point[0]["last_reviewed_at"] == (MONDAY_MORNING + timedelta(minutes=20)).isoformat()
    conn.close()


def test_a_holding_under_two_percent_is_never_due_on_schedule(tmp_path: Path) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    snapshot = snapshot_at(
        conn, tmp_path, MONDAY_MORNING, {"NVDA": (0.1, 200, 200), "F": (0.1, 10, 10)}
    )

    due = holdings_due(conn, snapshot, MONDAY_MORNING)

    assert [(item["ticker"], item["reasons"]) for item in due] == [
        ("NVDA", ["scheduled_review", "range_missing"]),
        ("F", ["range_missing"]),
    ]
    conn.close()


def test_a_trigger_driven_review_holds_off_the_schedule_and_other_triggers_for_three_days(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    snapshot = snapshot_at(conn, tmp_path, MONDAY_MORNING, {"NVDA": (0.1, 200, 200)})
    episode = live_holding_episodes(conn, ACCOUNT, MONDAY_MORNING)["NVDA"]["episode_id"]
    review(
        conn, episode, "NVDA", MONDAY_MORNING + timedelta(minutes=20), reasons=["scheduled_review"]
    )
    insert_trigger(conn, "price_move", "NVDA", date(2026, 9, 22), date(2026, 9, 22), {})
    wednesday_morning = MONDAY_MORNING + timedelta(days=2)
    friday_midday = MONDAY_MORNING + timedelta(days=4, hours=3)
    next_monday = MONDAY_MORNING + timedelta(days=7)

    triggered = holdings_due(conn, snapshot, wednesday_morning)
    review(conn, episode, "NVDA", wednesday_morning + timedelta(minutes=30), reasons=["price_move"])
    insert_trigger(conn, "volume_spike", "NVDA", date(2026, 9, 23), date(2026, 9, 23), {})
    cooling_down = holdings_due(conn, snapshot, friday_midday)
    cooled = holdings_due(conn, snapshot, next_monday)

    assert [item["reasons"] for item in triggered] == [["price_move"]]
    assert cooling_down == []
    assert [item["reasons"] for item in cooled] == [["scheduled_review", "volume_spike"]]
    conn.close()


def test_reported_earnings_since_the_last_review_make_a_holding_due(tmp_path: Path) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    snapshot = snapshot_at(conn, tmp_path, MONDAY_MORNING, {"NVDA": (0.1, 200, 200)})
    episode = live_holding_episodes(conn, ACCOUNT, MONDAY_MORNING)["NVDA"]["episode_id"]
    review(conn, episode, "NVDA", MONDAY_MORNING + timedelta(minutes=20))
    conn.execute(
        "INSERT INTO calendar_events (event_type, ticker, event_date, source, fetched_at) "
        "VALUES ('earnings', 'NVDA', '2026-09-22', 'test', '2026-09-01T00:00:00+00:00')"
    )

    due = holdings_due(conn, snapshot, MONDAY_MORNING + timedelta(days=2))

    assert [item["reasons"] for item in due] == [["earnings_reported"]]
    conn.close()


def test_x_headlines_bearing_on_a_holding_are_listed_for_triage_until_triaged(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    snapshot = snapshot_at(conn, tmp_path, MONDAY_MORNING, {"NVDA": (0.1, 200, 200)})
    episode = live_holding_episodes(conn, ACCOUNT, MONDAY_MORNING)["NVDA"]["episode_id"]
    review(conn, episode, "NVDA", MONDAY_MORNING + timedelta(minutes=20))
    x_post(conn, "1", "Blackwell racks are sold out through next year", "headline", ["NVDA"])
    x_post(conn, "2", "NVDAX is a different fund", "headline", [])
    x_post(conn, "3", "Hopper rental prices are firming", "notable", ["NVDA"])
    wednesday_morning = MONDAY_MORNING + timedelta(days=2)

    listed = holdings_due(conn, snapshot, wednesday_morning)
    conn.execute(
        "INSERT INTO x_triage VALUES ('1', 'NVDA', ?, 0, 'Already in the thesis.', 'attempt', ?)",
        (ACCOUNT, wednesday_morning.isoformat()),
    )
    triaged = holdings_due(conn, snapshot, wednesday_morning)

    assert [
        (item["reasons"], [post["post_id"] for post in item["x_headlines"]]) for item in listed
    ] == [([], ["1"])]
    assert triaged == []
    conn.close()


def test_an_earnings_date_the_agent_read_outranks_a_nearby_feed_estimate(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    snapshot = snapshot_at(conn, tmp_path, MONDAY_MORNING, {"NVDA": (0.1, 200, 200)})
    episode = live_holding_episodes(conn, ACCOUNT, MONDAY_MORNING)["NVDA"]["episode_id"]
    review(conn, episode, "NVDA", MONDAY_MORNING + timedelta(minutes=20))
    conn.executemany(
        "INSERT INTO calendar_events (event_type, ticker, event_date, label, source, fetched_at) "
        "VALUES ('earnings', 'NVDA', ?, ?, ?, '2026-09-01T00:00:00+00:00')",
        [("2026-09-22", "estimated", "yfinance"), ("2026-10-08", "confirmed", "agent")],
    )

    outranked = holdings_due(conn, snapshot, MONDAY_MORNING + timedelta(days=2))
    conn.execute("UPDATE calendar_events SET label='estimated' WHERE source='agent'")
    both_estimates = holdings_due(conn, snapshot, MONDAY_MORNING + timedelta(days=2))

    assert outranked == []
    assert [item["reasons"] for item in both_estimates] == [["earnings_reported"]]
    conn.close()


def test_a_review_that_morning_covers_the_point_but_one_the_day_before_does_not(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    snapshot = snapshot_at(conn, tmp_path, MONDAY_MORNING, {"NVDA": (0.1, 200, 200)})
    episode = live_holding_episodes(conn, ACCOUNT, MONDAY_MORNING)["NVDA"]["episode_id"]
    wednesday_midday = MONDAY_MORNING + timedelta(days=2, hours=3)
    review(conn, episode, "NVDA", MONDAY_MORNING + timedelta(days=1, hours=1))

    a_day_and_more_before = holdings_due(conn, snapshot, wednesday_midday)
    review(conn, episode, "NVDA", MONDAY_MORNING + timedelta(days=2, minutes=5))
    same_morning = holdings_due(conn, snapshot, wednesday_midday)

    assert [item["reasons"] for item in a_day_and_more_before] == [["scheduled_review"]]
    assert same_morning == []
    conn.close()


def test_a_first_close_15_percent_under_cost_is_a_trigger_and_40_percent_overrides_the_cooldown(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    snapshot_at(conn, tmp_path, MONDAY_MORNING, {"F": (0.1, 10, 9)})
    episode = live_holding_episodes(conn, ACCOUNT, MONDAY_MORNING)["F"]["episode_id"]
    review(conn, episode, "F", MONDAY_MORNING + timedelta(minutes=30))
    tuesday = MONDAY_MORNING + timedelta(days=1)
    down_20 = snapshot_at(conn, tmp_path, tuesday, {"F": (0.1, 10, 8)})

    crossed_15 = holdings_due(conn, down_20, tuesday + timedelta(hours=1))
    review(
        conn,
        episode,
        "F",
        tuesday + timedelta(hours=1, minutes=30),
        reasons=["down_15_percent_from_cost"],
    )
    wednesday = tuesday + timedelta(days=1)
    down_45 = snapshot_at(conn, tmp_path, wednesday, {"F": (0.1, 10, 5.5)})
    crossed_40 = holdings_due(conn, down_45, wednesday + timedelta(hours=1))

    assert [item["reasons"] for item in crossed_15] == [["down_15_percent_from_cost"]]
    assert [item["reasons"] for item in crossed_40] == [["down_40_percent_from_cost"]]
    conn.close()


def test_an_invalidated_holding_stays_due_until_a_sale_goes_through(tmp_path: Path) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    snapshot = snapshot_at(conn, tmp_path, MONDAY_MORNING, {"NVDA": (0.1, 200, 200)})
    episode = live_holding_episodes(conn, ACCOUNT, MONDAY_MORNING)["NVDA"]["episode_id"]
    review(conn, episode, "NVDA", MONDAY_MORNING + timedelta(minutes=20), state="invalidated")
    # Monday midday: the sale is still live in the session it was decided in.
    monday_midday = MONDAY_MORNING + timedelta(hours=3)

    before = holdings_due(conn, snapshot, monday_midday)
    conn.execute(
        "INSERT INTO order_intents (order_intent_id, decision_id, created_at, ticker, side, "
        "execution_mode, execution_profile_id, intent_json) "
        "VALUES ('sell', 'decision', ?, 'NVDA', 'SELL', 'LIVE', 'codex', '{}')",
        ((MONDAY_MORNING + timedelta(hours=1)).isoformat(),),
    )
    after = holdings_due(conn, snapshot, monday_midday)
    conn.execute(
        "INSERT INTO broker_execution_records (broker_execution_record_id, order_intent_id, "
        "execution_packet_id, execution_profile_id, account_alias, submitted_at, ticker, side, "
        "status, broker_order_id, record_json) VALUES ('ber_sell', 'sell', 'ep', 'codex', "
        "'codex-agentic', ?, 'NVDA', 'SELL', 'SUBMITTED', 'rh-1', '{}')",
        ((MONDAY_MORNING + timedelta(hours=1)).isoformat(),),
    )
    conn.execute(
        "INSERT INTO broker_execution_events (broker_event_id, broker_execution_record_id, "
        "order_intent_id, execution_packet_id, execution_profile_id, status, occurred_at, "
        "detail, event_json) VALUES ('bev', 'ber_sell', 'sell', 'ep', 'codex', 'FAILED', ?, "
        "'', '{}')",
        ((MONDAY_MORNING + timedelta(hours=1)).isoformat(),),
    )
    failed = holdings_due(conn, snapshot, monday_midday)

    assert [item["reasons"] for item in before] == [["invalidated_without_exit"]]
    assert after == []
    assert [item["reasons"] for item in failed] == [["invalidated_without_exit"]]
    conn.close()


def test_the_thesis_range_triggers_at_fully_priced_and_demands_a_sale_when_overpriced(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    snapshot_at(conn, tmp_path, MONDAY_MORNING, {"NVDA": (0.1, 200, 200)})
    episode = live_holding_episodes(conn, ACCOUNT, MONDAY_MORNING)["NVDA"]["episode_id"]
    review(conn, episode, "NVDA", MONDAY_MORNING + timedelta(minutes=20), prices=(230, 260, 150))
    tuesday = MONDAY_MORNING + timedelta(days=1)
    fully_priced = snapshot_at(conn, tmp_path, tuesday, {"NVDA": (0.1, 200, 240)})
    overpriced = snapshot_at(
        conn, tmp_path, tuesday + timedelta(hours=1), {"NVDA": (0.1, 200, 265)}
    )

    reached = holdings_due(conn, fully_priced, tuesday + timedelta(minutes=30))
    beyond = holdings_due(conn, overpriced, tuesday + timedelta(hours=1, minutes=30))
    conn.execute(
        "INSERT INTO order_intents (order_intent_id, decision_id, created_at, ticker, side, "
        "execution_mode, execution_profile_id, intent_json) "
        "VALUES ('trim', 'trim', ?, 'NVDA', 'SELL', 'LIVE', 'codex', '{}')",
        ((tuesday + timedelta(hours=1, minutes=10)).isoformat(),),
    )
    trimmed = holdings_due(conn, overpriced, tuesday + timedelta(hours=1, minutes=30))

    assert [item["reasons"] for item in reached] == [["realization_reached"]]
    assert [item["reasons"] for item in beyond] == [
        ["realization_reached", "above_realization_range"]
    ]
    assert [item["reasons"] for item in trimmed] == [["realization_reached"]]
    conn.close()


def test_a_close_at_the_invalidation_price_is_due_regardless_of_a_cooldown(tmp_path: Path) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    snapshot_at(conn, tmp_path, MONDAY_MORNING, {"F": (0.1, 10, 9)})
    episode = live_holding_episodes(conn, ACCOUNT, MONDAY_MORNING)["F"]["episode_id"]
    review(
        conn,
        episode,
        "F",
        MONDAY_MORNING + timedelta(minutes=20),
        reasons=["price_move"],
        prices=(12, 14, 8),
    )
    broken = snapshot_at(conn, tmp_path, MONDAY_MORNING + timedelta(hours=2), {"F": (0.1, 10, 7.9)})

    due = holdings_due(conn, broken, MONDAY_MORNING + timedelta(hours=3))

    assert [item["reasons"] for item in due] == [["below_invalidation_price"]]
    conn.close()


def test_the_latest_statement_of_a_holding_range_wins(tmp_path: Path) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    snapshot_at(conn, tmp_path, MONDAY_MORNING, {"NVDA": (0.1, 200, 200)})
    episode = live_holding_episodes(conn, ACCOUNT, MONDAY_MORNING)["NVDA"]["episode_id"]

    def decided(decision_id: str, action: str, at: datetime, low: float) -> None:
        record = {
            "realization_price_low": low,
            "realization_price_high": low + 40,
            "invalidation_price": 150.0,
        }
        conn.execute(
            "INSERT INTO decision_records VALUES (?, ?, 'NVDA', ?, ?, '')",
            (decision_id, at.isoformat(), action, json.dumps(record)),
        )
        conn.execute(
            "INSERT INTO order_intents (order_intent_id, decision_id, created_at, ticker, side, "
            "execution_mode, execution_profile_id, intent_json) "
            "VALUES (?, ?, ?, 'NVDA', 'BUY', 'LIVE', 'codex', '{}')",
            (decision_id, decision_id, at.isoformat()),
        )

    decided("buy", "BUY", MONDAY_MORNING - timedelta(minutes=5), 230)
    bought = thesis_prices(conn, ACCOUNT, "codex", "NVDA", episode, MONDAY_MORNING)
    review(conn, episode, "NVDA", MONDAY_MORNING + timedelta(hours=1), prices=(250, 280, 170))
    reviewed = thesis_prices(
        conn, ACCOUNT, "codex", "NVDA", episode, MONDAY_MORNING + timedelta(hours=2)
    )
    decided("add", "ADD", MONDAY_MORNING + timedelta(hours=3), 270)
    added = thesis_prices(
        conn, ACCOUNT, "codex", "NVDA", episode, MONDAY_MORNING + timedelta(hours=4)
    )

    assert [item and item["realization_price_low"] for item in (bought, reviewed, added)] == [
        230,
        250,
        270,
    ]
    conn.close()


def close_bar(conn: sqlite3.Connection, ticker: str, day: str, close: float) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO daily_prices VALUES (?, ?, ?, ?, ?, ?, NULL, 0, 'test', ?)",
        (ticker, day, close, close, close, close, day),
    )


def test_a_5_percent_move_since_the_last_close_counts_the_same_day(tmp_path: Path) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    snapshot_at(conn, tmp_path, MONDAY_MORNING - timedelta(days=3), {"NVDA": (0.1, 200, 200)})
    episode = live_holding_episodes(conn, ACCOUNT, MONDAY_MORNING)["NVDA"]["episode_id"]
    review(conn, episode, "NVDA", MONDAY_MORNING - timedelta(days=3, hours=-1))
    close_bar(conn, "NVDA", "2026-09-18", 200.0)
    quiet = snapshot_at(conn, tmp_path, MONDAY_MORNING, {"NVDA": (0.1, 200, 204)})
    calm = holdings_due(conn, quiet, MONDAY_MORNING + timedelta(minutes=5))
    moved = snapshot_at(
        conn, tmp_path, MONDAY_MORNING + timedelta(hours=1), {"NVDA": (0.1, 200, 212)}
    )

    due = holdings_due(conn, moved, MONDAY_MORNING + timedelta(hours=1, minutes=5))

    assert calm == []
    assert [item["reasons"] for item in due] == [["price_move"]]
    conn.close()
