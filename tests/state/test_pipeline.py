from datetime import UTC, datetime

import pytest

from app.policy.decision_policy import PortfolioContext
from app.schemas.decision_record import RegimeState
from app.schemas.order_intent import ExecutionMode
from app.state.pipeline import DecisionStatus, append_status, process_decision
from app.storage.database import connect
from app.storage.records import get_decision_record, get_order_intent
from tests.fixtures.decision_records import decision_record_with, valid_decision_record_data


def test_approved_buy_runs_full_chain() -> None:
    conn = connect(":memory:")
    data = valid_decision_record_data()

    outcome = process_decision(conn, data)

    assert outcome.final_status == DecisionStatus.ORDER_INTENT_CREATED
    assert outcome.order_intent_id == "oi_dec_001"

    rows = conn.execute(
        "SELECT status FROM status_events WHERE subject_id = ? ORDER BY event_id",
        ("dec_001",),
    ).fetchall()
    statuses = [row[0] for row in rows]
    assert statuses == [
        DecisionStatus.DECISION_RECORD_CREATED.value,
        DecisionStatus.SCHEMA_VALIDATED.value,
        DecisionStatus.POLICY_APPROVED.value,
        DecisionStatus.ORDER_INTENT_CREATED.value,
    ]

    assert get_decision_record(conn, "dec_001") is not None
    assert get_order_intent(conn, "oi_dec_001") is not None


def test_schema_failure_is_an_outcome_not_a_crash() -> None:
    conn = connect(":memory:")
    data = valid_decision_record_data()
    data["ticker"] = "   "

    outcome = process_decision(conn, data)

    assert outcome.final_status == DecisionStatus.SCHEMA_FAILED
    row = conn.execute(
        "SELECT status, detail FROM status_events WHERE subject_id = ?",
        ("dec_001",),
    ).fetchone()
    assert row is not None
    assert row[0] == DecisionStatus.SCHEMA_FAILED.value
    assert row[1] != ""
    assert get_decision_record(conn, "dec_001") is None


def test_policy_rejection_stops_the_chain() -> None:
    conn = connect(":memory:")
    data = valid_decision_record_data()
    data["regime_state"] = "RED"

    outcome = process_decision(conn, data)

    assert outcome.final_status == DecisionStatus.POLICY_REJECTED
    assert outcome.policy_reasons
    assert outcome.order_intent_id is None
    assert get_order_intent(conn, "oi_dec_001") is None
    assert get_decision_record(conn, "dec_001") is not None


def test_non_actionable_approved_creates_no_intent() -> None:
    conn = connect(":memory:")
    record = decision_record_with(
        decision="HOLD",
        primary_theme_id=None,
        theme_ids=[],
        refined_thesis="",
    )
    data = record.model_dump(mode="json")

    outcome = process_decision(conn, data)

    assert outcome.final_status == DecisionStatus.POLICY_APPROVED
    assert outcome.order_intent_id is None


def test_rerun_is_idempotent() -> None:
    conn = connect(":memory:")
    data = valid_decision_record_data()

    outcome1 = process_decision(conn, data)
    outcome2 = process_decision(conn, data)

    assert outcome1 == outcome2

    record_count = conn.execute("SELECT COUNT(*) FROM decision_records").fetchone()[0]
    intent_count = conn.execute("SELECT COUNT(*) FROM order_intents").fetchone()[0]
    status_count = conn.execute("SELECT COUNT(*) FROM status_events").fetchone()[0]
    assert record_count == 1
    assert intent_count == 1
    assert status_count == 4


def test_rerun_returns_durable_approval_when_portfolio_context_has_changed() -> None:
    conn = connect(":memory:")
    data = valid_decision_record_data()
    first = process_decision(conn, data)
    full_quota = PortfolioContext(
        holdings_count=0,
        buy_add_trades_today=2,
        sell_trim_trades_today=0,
    )

    replay = process_decision(conn, data, portfolio=full_quota)

    assert replay == first
    assert conn.execute("SELECT COUNT(*) FROM status_events").fetchone()[0] == 4
    assert conn.execute("SELECT COUNT(*) FROM order_intents").fetchone()[0] == 1


def test_explicit_live_profile_is_preserved_on_created_intent() -> None:
    conn = connect(":memory:")

    outcome = process_decision(
        conn,
        valid_decision_record_data(),
        execution_mode=ExecutionMode.LIVE,
        execution_profile_id="codex",
    )

    intent = get_order_intent(conn, "oi_dec_001")
    assert outcome.final_status == DecisionStatus.ORDER_INTENT_CREATED
    assert intent is not None
    assert intent.execution_mode == ExecutionMode.LIVE
    assert intent.execution_profile_id == "codex"


def test_future_created_at_fails_before_record_is_saved() -> None:
    conn = connect(":memory:")
    data = valid_decision_record_data()
    data["created_at"] = datetime(2026, 6, 10, 12, 1, tzinfo=UTC)

    outcome = process_decision(
        conn,
        data,
        received_at=datetime(2026, 6, 10, 12, 0, tzinfo=UTC),
    )

    assert outcome.final_status == DecisionStatus.SCHEMA_FAILED
    assert get_decision_record(conn, "dec_001") is None
    status, detail = conn.execute(
        "SELECT status, detail FROM status_events WHERE subject_id = 'dec_001'"
    ).fetchone()
    assert status == DecisionStatus.SCHEMA_FAILED.value
    assert detail == "created_at_cannot_be_in_future"


def test_illegal_transition_raises() -> None:
    conn = connect(":memory:")

    with pytest.raises(ValueError):
        append_status(conn, "dec_999", DecisionStatus.POLICY_APPROVED)


def test_portfolio_context_flows_through() -> None:
    conn = connect(":memory:")
    data = valid_decision_record_data()
    portfolio = PortfolioContext(
        holdings_count=10,
        buy_add_trades_today=0,
        sell_trim_trades_today=0,
    )

    outcome = process_decision(conn, data, portfolio=portfolio)

    assert outcome.final_status == DecisionStatus.POLICY_REJECTED
    assert "max_holdings_reached" in outcome.policy_reasons


def test_true_regime_state_flows_through() -> None:
    conn = connect(":memory:")
    data = valid_decision_record_data()

    outcome = process_decision(conn, data, true_regime_state=RegimeState.RED)

    assert outcome.final_status == DecisionStatus.POLICY_REJECTED
    assert "regime_state_mismatch" in outcome.policy_reasons


def test_replay_cannot_change_execution_scope() -> None:
    conn = connect(":memory:")
    data = valid_decision_record_data()
    first = process_decision(conn, data)
    with pytest.raises(ValueError, match="scope mismatch"):
        process_decision(
            conn, data, execution_mode=ExecutionMode.LIVE, execution_profile_id="codex"
        )
    assert process_decision(conn, data) == first
    assert not conn.in_transaction
    conn.close()
