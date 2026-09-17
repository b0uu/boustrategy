from datetime import UTC, datetime
from typing import Any

from app.schemas.order_intent import ExecutionMode
from app.state.pipeline import process_decision
from app.storage.database import connect
from app.storage.watchlist import open_watchlist_entries
from tests.fixtures.decision_records import valid_decision_record_data

RECEIVED = datetime(2026, 9, 30, tzinfo=UTC)


def listing(decision_id: str, decision: str, day: int, **overrides: Any) -> dict[str, Any]:
    data = valid_decision_record_data()
    data.update(
        decision_id=decision_id,
        decision=decision,
        created_at=datetime(2026, 9, day, 15, tzinfo=UTC),
    )
    data.update(overrides)
    return data


def test_an_entry_keeps_its_listing_date_and_takes_the_latest_bound() -> None:
    conn = connect(":memory:")
    for decision_id, decision, day, extra in (
        ("w1", "WATCHLIST", 1, {"entry_price_max": 105.0}),
        ("w2", "WATCHLIST", 3, {"entry_price_max": 98.0}),
        ("w3", "WATCHLIST", 4, {"ticker": "AMD", "entry_price_max": 50.0}),
    ):
        process_decision(conn, listing(decision_id, decision, day, **extra), received_at=RECEIVED)

    entries = open_watchlist_entries(conn, "PAPER")

    assert sorted(entries) == ["AMD", "NVDA"]
    assert entries["NVDA"].listed_at.day == 1
    assert entries["NVDA"].restated_at.day == 3
    assert (entries["NVDA"].decision_id, entries["NVDA"].statements) == ("w2", 2)
    assert entries["NVDA"].entry_price_max == 98.0
    assert entries["AMD"].statements == 1


def test_acting_on_a_ticker_takes_it_off_the_watchlist() -> None:
    conn = connect(":memory:")
    for decision_id, decision, day, extra in (
        ("w1", "WATCHLIST", 1, {"entry_price_max": 105.0}),
        ("w2", "WATCHLIST", 1, {"ticker": "AMD", "entry_price_max": 50.0}),
        ("b1", "BUY", 5, {}),
        ("p1", "PASS", 5, {"ticker": "AMD"}),
    ):
        process_decision(conn, listing(decision_id, decision, day, **extra), received_at=RECEIVED)

    assert open_watchlist_entries(conn, "PAPER") == {}


def test_a_later_listing_reopens_a_closed_entry() -> None:
    conn = connect(":memory:")
    for decision_id, decision, day, extra in (
        ("w1", "WATCHLIST", 1, {"entry_price_max": 105.0}),
        ("p1", "PASS", 3, {}),
        ("w2", "WATCHLIST", 6, {"entry_price_max": 90.0}),
    ):
        process_decision(conn, listing(decision_id, decision, day, **extra), received_at=RECEIVED)

    entries = open_watchlist_entries(conn, "PAPER")

    assert entries["NVDA"].listed_at.day == 6
    assert entries["NVDA"].statements == 1


def test_entries_keep_execution_modes_apart() -> None:
    conn = connect(":memory:")
    process_decision(
        conn,
        listing("w1", "WATCHLIST", 1, entry_price_max=105.0),
        received_at=RECEIVED,
        execution_mode=ExecutionMode.LIVE,
        execution_profile_id="codex",
    )

    assert open_watchlist_entries(conn, "PAPER") == {}
    assert sorted(open_watchlist_entries(conn, "LIVE", "codex")) == ["NVDA"]
    assert open_watchlist_entries(conn, "LIVE", "other") == {}
