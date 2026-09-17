import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from app.policy.decision_policy import PortfolioContext
from app.prices.cache import upsert_daily_prices
from app.reason.worker import unanswered_short_calls
from app.schemas.decision_record import InvestmentDecisionRecord, ShortRemovalConditions
from app.schemas.order_intent import ExecutionMode
from app.schemas.runtime import AuthoredOutput
from app.state.pipeline import DecisionStatus, process_decision
from app.storage.database import connect
from app.storage.short_watchlist import (
    ShortCall,
    ShortDeclaration,
    short_call_report,
    short_removal_status,
    short_watchlist_history,
)
from tests.fixtures.decision_records import valid_decision_record_data
from tests.prices.test_cache import price_bar
from tests.reason.test_runtime import paper_run

RECEIVED = datetime(2026, 9, 30, tzinfo=UTC)
CONDITIONS = ShortRemovalConditions(cover_below=96.0, stop_above=144.0, review_by=date(2026, 10, 1))


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
    if decision == "SHORT_WATCHLIST":
        data["short_removal_conditions"] = {
            "cover_below": round(price * 0.8, 2),
            "stop_above": round(price * 1.2, 2),
            "review_by": "2026-10-01",
        }
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


def open_call(conditions: ShortRemovalConditions | None = CONDITIONS) -> ShortCall:
    return ShortCall(
        ticker="NVDA",
        declarations=[
            ShortDeclaration(
                decision_id="s1",
                declared_at=datetime(2026, 9, 1, 15, tzinfo=UTC),
                reference_price=120.0,
                thesis_invalidation_criteria=["Backlog re-accelerates."],
                removal_conditions=conditions,
            )
        ],
    )


def test_removal_status_names_each_condition_the_price_has_already_met() -> None:
    before = date(2026, 9, 20)

    assert short_removal_status(open_call(), 110.0, before) == []
    assert short_removal_status(open_call(), 96.0, before) == ["cover_below_hit"]
    assert short_removal_status(open_call(), 95.0, before) == ["cover_below_hit"]
    assert short_removal_status(open_call(), 144.0, before) == ["stop_above_hit"]
    assert short_removal_status(open_call(), None, before) == []
    assert short_removal_status(open_call(), 110.0, date(2026, 10, 1)) == ["review_by_reached"]
    assert short_removal_status(open_call(), 95.0, date(2026, 10, 2)) == [
        "cover_below_hit",
        "review_by_reached",
    ]


def test_a_removed_or_unconditioned_call_is_never_due() -> None:
    removed = open_call()
    removed.removed_at = datetime(2026, 9, 10, tzinfo=UTC)

    assert short_removal_status(removed, 95.0, date(2026, 10, 2)) == []
    assert short_removal_status(open_call(conditions=None), 95.0, date(2026, 10, 2)) == []


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


def test_a_due_short_call_must_be_answered_before_the_review_is_accepted(tmp_path: Path) -> None:
    conn = connect(tmp_path / "source.db")
    run = paper_run(conn, tmp_path)
    process_decision(
        conn,
        short_call("s1", "SHORT_WATCHLIST", 1, 120.0),
        paper_context(conn),
        received_at=RECEIVED,
    )
    ignored = AuthoredOutput(public_summary="No action.")
    # 2026-10-02 is past the call's 2026-10-01 backstop, so the review owes it an answer.
    due_date = date(2026, 10, 2)

    unanswered = unanswered_short_calls(conn, run, due_date, ignored)
    before_due = unanswered_short_calls(conn, run, date(2026, 9, 20), ignored)
    removed = AuthoredOutput(
        decisions=[
            InvestmentDecisionRecord.model_validate(
                short_call("r1", "SHORT_WATCHLIST_REMOVE", 2, 118.0)
            )
        ],
        public_summary="Removed the call.",
    )

    assert unanswered is not None and "due for removal" in unanswered and "NVDA" in unanswered
    assert before_due is None
    assert unanswered_short_calls(conn, run, due_date, removed) is None
    conn.close()


def test_report_scores_a_removed_call_at_its_removal_and_an_open_one_at_the_last_close() -> None:
    conn = connect(":memory:")
    upsert_daily_prices(conn, [price_bar("AMD", date(2026, 9, 9), 90.0)])
    for decision_id, decision, day, price, ticker in (
        ("s1", "SHORT_WATCHLIST", 1, 120.0, "NVDA"),
        ("r1", "SHORT_WATCHLIST_REMOVE", 5, 95.0, "NVDA"),
        ("s2", "SHORT_WATCHLIST", 8, 101.0, "AMD"),
    ):
        process_decision(
            conn,
            short_call(decision_id, decision, day, price, ticker=ticker),
            paper_context(conn),
            received_at=RECEIVED,
        )

    nvda, amd = short_call_report(conn, "PAPER", None, date(2026, 9, 10))

    # A short gains as the price falls: NVDA 120 -> 95 is +20.83%, AMD 101 -> 90 is +10.89%.
    assert (nvda["status"], nvda["short_return_percent"], nvda["days_listed"]) == (
        "removed",
        20.8333,
        4,
    )
    assert (nvda["end_price"], nvda["ended_at"]) == (95.0, "2026-09-05")
    assert nvda["decision_ids"] == ["s1", "r1"]
    assert (amd["status"], amd["short_return_percent"], amd["days_listed"]) == ("open", 10.8911, 2)
    assert (amd["end_price"], amd["ended_at"], amd["due"]) == (90.0, "2026-09-09", [])


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
