import json
import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from app.broker.collector import collect_snapshot
from app.schemas.live_execution import LivePortfolioSnapshot
from app.schemas.public_authoring import ThesisReview
from app.storage.database import connect
from app.storage.holding_reviews import holdings_due, latest_review_point, live_holding_episodes
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
        ),
    )


def x_post(
    conn: sqlite3.Connection, post_id: str, text: str, rank: str, tickers: list[str]
) -> None:
    conn.execute(
        "INSERT INTO x_posts (post_id, handle, posted_at, text, url, fetched_at) "
        "VALUES (?, 'analyst', '2026-09-22T12:00:00+00:00', ?, ?, '2026-09-22T12:05:00+00:00')",
        (post_id, text, f"https://x.com/analyst/status/{post_id}"),
    )
    conn.execute(
        "INSERT INTO x_route_decisions "
        "(post_id, run_id, route, rank, reason, predictor, decided_at, tickers) "
        "VALUES (?, 'run', 'digest', ?, '', 'predictor', '2026-09-22T13:00:00+00:00', ?)",
        (post_id, rank, json.dumps(tickers)),
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


def test_review_points_are_monday_morning_and_wednesday_and_friday_midday() -> None:
    wednesday_midday = datetime(2026, 9, 23, 17, 0, tzinfo=UTC)
    wednesday_morning = datetime(2026, 9, 23, 14, 0, tzinfo=UTC)
    sunday = datetime(2026, 9, 27, 16, 0, tzinfo=UTC)

    points = [
        latest_review_point(moment) for moment in (wednesday_midday, wednesday_morning, sunday)
    ]

    assert [point.isoformat() for point in points] == [
        "2026-09-23T12:00:00-04:00",
        "2026-09-21T09:00:00-04:00",
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

    assert [item["reasons"] for item in never_reviewed] == [["scheduled_review"]]
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

    assert [item["ticker"] for item in due] == ["NVDA"]
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


def test_reported_earnings_and_an_x_post_tagged_with_the_holding_make_it_due(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    snapshot = snapshot_at(conn, tmp_path, MONDAY_MORNING, {"NVDA": (0.1, 200, 200)})
    episode = live_holding_episodes(conn, ACCOUNT, MONDAY_MORNING)["NVDA"]["episode_id"]
    review(conn, episode, "NVDA", MONDAY_MORNING + timedelta(minutes=20))
    conn.execute(
        "INSERT INTO calendar_events (event_type, ticker, event_date, source, fetched_at) "
        "VALUES ('earnings', 'NVDA', '2026-09-22', 'test', '2026-09-01T00:00:00+00:00')"
    )
    x_post(conn, "1", "NVDAX is a different fund", "headline", [])
    earnings_only = holdings_due(conn, snapshot, MONDAY_MORNING + timedelta(days=2))
    x_post(conn, "2", "Blackwell racks are sold out through next year", "notable", ["NVDA"])

    due = holdings_due(conn, snapshot, MONDAY_MORNING + timedelta(days=2))

    assert [item["reasons"] for item in earnings_only] == [["earnings_reported"]]
    assert [item["reasons"] for item in due] == [["earnings_reported", "x_digest"]]
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

    due = holdings_due(conn, snapshot, MONDAY_MORNING + timedelta(days=2))

    assert due == []
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


def test_an_invalidated_holding_stays_due_until_it_is_sold(tmp_path: Path) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    snapshot = snapshot_at(conn, tmp_path, MONDAY_MORNING, {"NVDA": (0.1, 200, 200)})
    episode = live_holding_episodes(conn, ACCOUNT, MONDAY_MORNING)["NVDA"]["episode_id"]
    review(conn, episode, "NVDA", MONDAY_MORNING + timedelta(minutes=20), state="invalidated")
    tuesday_morning = MONDAY_MORNING + timedelta(days=1)

    before = holdings_due(conn, snapshot, tuesday_morning)
    conn.execute(
        "INSERT INTO order_intents (order_intent_id, decision_id, created_at, ticker, side, "
        "execution_mode, execution_profile_id, intent_json) "
        "VALUES ('sell', 'decision', ?, 'NVDA', 'SELL', 'LIVE', 'codex', '{}')",
        ((MONDAY_MORNING + timedelta(hours=1)).isoformat(),),
    )
    after = holdings_due(conn, snapshot, tuesday_morning)

    assert [item["reasons"] for item in before] == [["invalidated_without_exit"]]
    assert after == []
    conn.close()
