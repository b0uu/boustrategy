from datetime import UTC, date, datetime

import pytest

from app.schemas.live_execution import ExecutionProfile, LivePortfolioSnapshot
from app.schemas.reasoning_run import ReasoningRun
from app.storage.database import connect
from app.storage.records import (
    complete_reasoning_run,
    get_live_portfolio_snapshot,
    get_reasoning_run,
    save_live_portfolio_snapshot,
    save_reasoning_run,
)


def _profile(profile_id: str = "codex") -> ExecutionProfile:
    return ExecutionProfile(
        execution_profile_id=profile_id,
        agent_provider="CODEX",
        account_alias=f"{profile_id}-agentic",
        broker_account_fingerprint="0123456789abcdef",
        enabled=True,
        max_order_notional=20,
        max_quote_age_seconds=60,
        max_spread_bps=50,
    )


def _snapshot(profile_id: str = "codex") -> LivePortfolioSnapshot:
    return LivePortfolioSnapshot(
        portfolio_snapshot_id=f"snap_{profile_id}",
        execution_profile_id=profile_id,
        broker_account_fingerprint="0123456789abcdef",
        captured_at=datetime(2026, 8, 27, 20, tzinfo=UTC),
        account_equity=100,
        buying_power=80,
        positions=[],
    )


def _run() -> ReasoningRun:
    return ReasoningRun(
        reasoning_run_id="rr_2026-08-27_close_codex",
        session_date=date(2026, 8, 27),
        slot="close",
        execution_profile_id="codex",
        model_label="Codex",
        shared_bundle_path="data/reason/2026-08-27/shared_bundle.md",
        shared_bundle_sha256="a" * 64,
        portfolio_snapshot_id="snap_codex",
        started_at=datetime(2026, 8, 27, 20, tzinfo=UTC),
    )


def test_snapshot_store_is_idempotent_and_profile_bound() -> None:
    conn = connect(":memory:")
    snapshot = _snapshot()

    assert save_live_portfolio_snapshot(conn, snapshot, _profile()) is True
    assert save_live_portfolio_snapshot(conn, snapshot, _profile()) is False
    assert get_live_portfolio_snapshot(conn, snapshot.portfolio_snapshot_id) == snapshot
    with pytest.raises(ValueError, match="profile"):
        save_live_portfolio_snapshot(conn, _snapshot("claude"), _profile())


def test_snapshot_can_be_saved_before_profile_is_enabled() -> None:
    conn = connect(":memory:")
    profile = _profile().model_copy(update={"enabled": False})
    snapshot = _snapshot()

    assert save_live_portfolio_snapshot(conn, snapshot, profile) is True
    assert get_live_portfolio_snapshot(conn, snapshot.portfolio_snapshot_id) == snapshot


def test_reasoning_run_store_and_terminal_transition_are_append_only() -> None:
    conn = connect(":memory:")
    run = _run()
    completed = ReasoningRun.model_validate(
        {
            **run.model_dump(),
            "result": "NO_ACTION",
            "completed_at": datetime(2026, 8, 27, 21, tzinfo=UTC),
            "public_summary": "No action.",
        }
    )

    assert save_reasoning_run(conn, run) is True
    assert save_reasoning_run(conn, run) is False
    assert complete_reasoning_run(conn, completed).result == "NO_ACTION"
    assert complete_reasoning_run(conn, completed).result == "NO_ACTION"
    assert get_reasoning_run(conn, run.reasoning_run_id) == completed

    failed = ReasoningRun.model_validate(
        {**completed.model_dump(), "result": "FAILED", "public_summary": "Failed."}
    )
    with pytest.raises(ValueError, match="already complete"):
        complete_reasoning_run(conn, failed)


def test_authored_run_completion_requires_exact_linked_decisions() -> None:
    conn = connect(":memory:")
    run = _run()
    save_reasoning_run(conn, run)
    conn.execute(
        "INSERT INTO reasoning_run_decisions VALUES (?, ?, ?)",
        (run.reasoning_run_id, f"{run.reasoning_run_id}_dec_001", "snap_codex"),
    )
    completed = ReasoningRun.model_validate(
        {
            **run.model_dump(),
            "result": "DECISIONS_AUTHORED",
            "completed_at": datetime(2026, 8, 27, 21, tzinfo=UTC),
            "public_summary": "One decision.",
            "decision_ids": [f"{run.reasoning_run_id}_dec_001"],
        }
    )

    assert complete_reasoning_run(conn, completed) == completed


def test_optional_snapshot_reporting_enters_immutable_ledger() -> None:
    from app.schemas.reporting import ValuationObservation

    conn = connect(":memory:")
    base = _snapshot()
    report = ValuationObservation(
        observation_id="report",
        external_event_id="report",
        mode="live",
        account_id=base.broker_account_fingerprint,
        occurred_at=base.captured_at,
        recorded_at=base.captured_at,
        equity="100",
        cash="100",
        positions=[],
        complete=True,
    )
    snapshot = LivePortfolioSnapshot.model_validate({**base.model_dump(), "reporting": report})
    assert save_live_portfolio_snapshot(conn, snapshot, _profile())
    assert conn.execute("SELECT COUNT(*) FROM reporting_observations").fetchone()[0] == 1
    assert not save_live_portfolio_snapshot(conn, snapshot, _profile())
    assert conn.execute("SELECT COUNT(*) FROM reporting_observations").fetchone()[0] == 1
