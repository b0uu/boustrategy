import sqlite3
from datetime import UTC, datetime
from typing import Any

from app.policy.decision_policy import PortfolioContext
from app.schemas.order_intent import ExecutionMode
from app.state.pipeline import DecisionStatus, process_decision
from app.storage.database import connect
from app.storage.short_watchlist import short_watchlist_history
from tests.fixtures.decision_records import valid_decision_record_data

RECEIVED = datetime(2026, 9, 30, tzinfo=UTC)


def short_call(
    decision_id: str, decision: str, day: int, price: float, **overrides: Any
) -> dict[str, Any]:
    data = valid_decision_record_data()
    data.update(
        decision_id=decision_id,
        decision=decision,
        created_at=datetime(2026, 9, day, 15, tzinfo=UTC),
        counter_thesis="Bull case: backlog could re-accelerate.",
        what_is_priced_in="Consensus still prices a second-half recovery.",
        proposed_target_weight=0.0,
        final_target_weight=0.0,
        reference_price=price,
        reference_price_at=datetime(2026, 9, day, 14, 55, tzinfo=UTC),
    )
    data.update(overrides)
    return data


def paper_context(conn: sqlite3.Connection) -> PortfolioContext:
    return PortfolioContext(
        holdings_count=0,
        buy_add_trades_today=0,
        sell_trim_trades_today=0,
        short_watchlist_tickers=[
            call.ticker
            for call in short_watchlist_history(conn, "PAPER")
            if call.removed_at is None
        ],
    )


def test_history_dates_each_declaration_and_removal() -> None:
    conn = connect(":memory:")
    for decision_id, decision, day, price in (
        ("s1", "SHORT_WATCHLIST", 1, 120.0),
        ("s2", "SHORT_WATCHLIST", 3, 118.0),
        ("r1", "SHORT_WATCHLIST_REMOVE", 5, 95.0),
        ("s3", "SHORT_WATCHLIST", 8, 101.0),
    ):
        outcome = process_decision(
            conn,
            short_call(decision_id, decision, day, price),
            paper_context(conn),
            received_at=RECEIVED,
        )
        assert outcome.final_status == DecisionStatus.POLICY_APPROVED

    first, second = short_watchlist_history(conn, "PAPER")

    assert first.ticker == "NVDA"
    assert [item.declared_at.day for item in first.declarations] == [1, 3]
    assert [item.reference_price for item in first.declarations] == [120.0, 118.0]
    assert (first.removed_at and first.removed_at.day, first.removal_price) == (5, 95.0)
    assert first.removal_decision_id == "r1"
    assert [item.decision_id for item in second.declarations] == ["s3"]
    assert second.removed_at is None


def test_history_skips_rejected_removals_and_keeps_modes_apart() -> None:
    conn = connect(":memory:")

    rejected = process_decision(
        conn,
        short_call("r1", "SHORT_WATCHLIST_REMOVE", 2, 95.0),
        paper_context(conn),
        received_at=RECEIVED,
    )
    process_decision(
        conn,
        short_call("s1", "SHORT_WATCHLIST", 3, 120.0),
        received_at=RECEIVED,
        execution_mode=ExecutionMode.LIVE,
        execution_profile_id="codex",
    )

    assert rejected.policy_reasons == ["short_watchlist_entry_missing"]
    assert short_watchlist_history(conn, "PAPER") == []
    assert [call.ticker for call in short_watchlist_history(conn, "LIVE", "codex")] == ["NVDA"]
    assert short_watchlist_history(conn, "LIVE", "other") == []
