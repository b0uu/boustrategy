import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.broker.collector import collect_snapshot
from app.schemas.live_execution import LivePortfolioSnapshot
from app.schemas.public_authoring import ThesisReview
from app.storage.database import connect
from app.storage.holding_reviews import holdings_due, latest_review_point, live_holding_episodes
from app.storage.public_records import save_thesis_review
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


def review(conn: sqlite3.Connection, episode_id: str, ticker: str, at: datetime) -> None:
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
            state="intact",
            summary="Still holds.",
        ),
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


def test_a_holding_down_40_percent_is_due_every_session_until_reviewed_that_day(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    friday = MONDAY_MORNING - timedelta(days=3)
    snapshot = snapshot_at(conn, tmp_path, friday, {"F": (0.1, 10, 6)})
    episode = live_holding_episodes(conn, ACCOUNT, friday)["F"]["episode_id"]
    review(conn, episode, "F", friday + timedelta(hours=1))
    monday_midday = MONDAY_MORNING + timedelta(hours=3)

    before = holdings_due(conn, snapshot, monday_midday)
    review(conn, episode, "F", MONDAY_MORNING + timedelta(hours=1))
    after = holdings_due(conn, snapshot, monday_midday)

    assert [item["reasons"] for item in before] == [["down_40_percent_from_cost"]]
    assert after == []
    conn.close()
