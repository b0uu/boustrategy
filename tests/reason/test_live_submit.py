import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.reason.run import submit_decision
from app.schemas.live_execution import ExecutionProfile, LivePortfolioSnapshot
from app.schemas.order_intent import ExecutionMode
from app.schemas.reasoning_run import ReasoningRun, ReasoningRunResult
from app.storage.database import connect
from app.storage.records import save_live_portfolio_snapshot, save_reasoning_run
from tests.fixtures.decision_records import valid_decision_record_data

RUN_ID = "rr_2026-06-10_close_codex"
SUBMITTED_AT = datetime(2026, 6, 10, 12, 3, tzinfo=UTC)


def _profile() -> ExecutionProfile:
    return ExecutionProfile(
        execution_profile_id="codex",
        agent_provider="CODEX",
        account_alias="codex-agentic",
        broker_account_fingerprint="0" * 16,
        enabled=True,
        max_order_notional=20,
        max_quote_age_seconds=60,
        max_spread_bps=50,
    )


def _prepare_live_boundary(conn: sqlite3.Connection, *, captured_at: datetime) -> None:
    snapshot = LivePortfolioSnapshot(
        portfolio_snapshot_id="snap_codex",
        execution_profile_id="codex",
        broker_account_fingerprint="0" * 16,
        captured_at=captured_at,
        account_equity=100,
        buying_power=100,
    )
    save_live_portfolio_snapshot(conn, snapshot, _profile())
    save_reasoning_run(
        conn,
        ReasoningRun(
            reasoning_run_id=RUN_ID,
            session_date=date(2026, 6, 10),
            slot="close",
            execution_profile_id="codex",
            model_label="Codex",
            shared_bundle_path="shared_bundle.md",
            shared_bundle_sha256="a" * 64,
            portfolio_snapshot_id="snap_codex",
            started_at=captured_at,
        ),
    )
    conn.execute(
        "INSERT OR IGNORE INTO regime_snapshots VALUES (?, ?, ?, ?, ?, ?)",
        ("2026-06-09", "GREEN", "GREEN", 5, "{}", "2026-06-09T20:00:00+00:00"),
    )
    conn.commit()


def _record() -> dict[str, object]:
    return {
        **valid_decision_record_data(),
        "decision_id": f"{RUN_ID}_dec_001",
    }


def test_live_submit_requires_run_and_fresh_namespaced_snapshot() -> None:
    conn = connect(":memory:")

    with pytest.raises(ValueError, match="missing reasoning run"):
        submit_decision(
            conn,
            _record(),
            date(2026, 6, 10),
            execution_mode=ExecutionMode.LIVE,
            execution_profile_id="codex",
            reasoning_run_id=RUN_ID,
            execution_profile=_profile(),
            submission_snapshot_id="snap_codex",
            submitted_at=SUBMITTED_AT,
        )

    _prepare_live_boundary(conn, captured_at=SUBMITTED_AT - timedelta(minutes=1))
    outcome = submit_decision(
        conn,
        _record(),
        date(2026, 6, 10),
        execution_mode=ExecutionMode.LIVE,
        execution_profile_id="codex",
        reasoning_run_id=RUN_ID,
        execution_profile=_profile(),
        submission_snapshot_id="snap_codex",
        submitted_at=SUBMITTED_AT,
    )

    assert outcome.order_intent_id == f"oi_{RUN_ID}_dec_001"
    assert conn.execute("SELECT COUNT(*) FROM reasoning_run_decisions").fetchone()[0] == 1
    assert conn.execute("SELECT execution_profile_id FROM order_intents").fetchone()[0] == "codex"


def test_live_submit_rejects_stale_snapshot_and_wrong_namespace() -> None:
    stale = connect(":memory:")
    _prepare_live_boundary(stale, captured_at=SUBMITTED_AT - timedelta(minutes=6))

    with pytest.raises(ValueError, match="stale"):
        submit_decision(
            stale,
            _record(),
            date(2026, 6, 10),
            execution_mode=ExecutionMode.LIVE,
            execution_profile_id="codex",
            reasoning_run_id=RUN_ID,
            execution_profile=_profile(),
            submission_snapshot_id="snap_codex",
            submitted_at=SUBMITTED_AT,
        )


def test_live_submit_requires_explicit_submission_snapshot() -> None:
    conn = connect(":memory:")
    _prepare_live_boundary(conn, captured_at=SUBMITTED_AT)

    with pytest.raises(ValueError, match="requires a fresh portfolio snapshot"):
        submit_decision(
            conn,
            _record(),
            date(2026, 6, 10),
            execution_mode=ExecutionMode.LIVE,
            execution_profile_id="codex",
            reasoning_run_id=RUN_ID,
            execution_profile=_profile(),
            submitted_at=SUBMITTED_AT,
        )


def test_live_submit_rejects_wrong_profile_and_account() -> None:
    conn = connect(":memory:")
    _prepare_live_boundary(conn, captured_at=SUBMITTED_AT)

    wrong_profile = _profile().model_copy(update={"execution_profile_id": "claude"})
    with pytest.raises(ValueError, match="profile mismatch"):
        submit_decision(
            conn,
            _record(),
            date(2026, 6, 10),
            execution_mode=ExecutionMode.LIVE,
            execution_profile_id="codex",
            reasoning_run_id=RUN_ID,
            execution_profile=wrong_profile,
            submission_snapshot_id="snap_codex",
            submitted_at=SUBMITTED_AT,
        )

    wrong_account = _profile().model_copy(update={"broker_account_fingerprint": "1" * 16})
    with pytest.raises(ValueError, match="account mismatch"):
        submit_decision(
            conn,
            _record(),
            date(2026, 6, 10),
            execution_mode=ExecutionMode.LIVE,
            execution_profile_id="codex",
            reasoning_run_id=RUN_ID,
            execution_profile=wrong_account,
            submission_snapshot_id="snap_codex",
            submitted_at=SUBMITTED_AT,
        )


def test_live_submit_retry_is_idempotent() -> None:
    conn = connect(":memory:")
    _prepare_live_boundary(conn, captured_at=SUBMITTED_AT)

    first = submit_decision(
        conn,
        _record(),
        date(2026, 6, 10),
        execution_mode=ExecutionMode.LIVE,
        execution_profile_id="codex",
        reasoning_run_id=RUN_ID,
        execution_profile=_profile(),
        submission_snapshot_id="snap_codex",
        submitted_at=SUBMITTED_AT,
    )
    second = submit_decision(
        conn,
        _record(),
        date(2026, 6, 10),
        execution_mode=ExecutionMode.LIVE,
        execution_profile_id="codex",
        reasoning_run_id=RUN_ID,
        execution_profile=_profile(),
        submission_snapshot_id="snap_codex",
        submitted_at=SUBMITTED_AT,
    )

    assert second == first
    assert conn.execute("SELECT COUNT(*) FROM reasoning_run_decisions").fetchone()[0] == 1


def test_live_submit_rolls_back_decision_writes_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = connect(":memory:")
    _prepare_live_boundary(conn, captured_at=SUBMITTED_AT)

    def fail_after_write(conn: sqlite3.Connection, *args: object, **kwargs: object) -> None:
        conn.execute(
            """
            INSERT INTO decision_records
                (decision_id, created_at, ticker, decision, record_json)
            VALUES ('partial', '2026-06-10', 'NVDA', 'BUY', '{}')
            """
        )
        raise RuntimeError("forced failure")

    monkeypatch.setattr("app.reason.run.process_decision", fail_after_write)

    with pytest.raises(RuntimeError, match="forced failure"):
        submit_decision(
            conn,
            _record(),
            date(2026, 6, 10),
            execution_mode=ExecutionMode.LIVE,
            execution_profile_id="codex",
            reasoning_run_id=RUN_ID,
            execution_profile=_profile(),
            submission_snapshot_id="snap_codex",
            submitted_at=SUBMITTED_AT,
        )

    assert conn.execute("SELECT COUNT(*) FROM decision_records").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM reasoning_run_decisions").fetchone()[0] == 0

    fresh = connect(":memory:")
    _prepare_live_boundary(fresh, captured_at=SUBMITTED_AT)
    record = _record()
    record["decision_id"] = "dec_001"
    with pytest.raises(ValueError, match="namespace"):
        submit_decision(
            fresh,
            record,
            date(2026, 6, 10),
            execution_mode=ExecutionMode.LIVE,
            execution_profile_id="codex",
            reasoning_run_id=RUN_ID,
            execution_profile=_profile(),
            submission_snapshot_id="snap_codex",
            submitted_at=SUBMITTED_AT,
        )


def test_live_submit_preserves_initial_snapshot_and_links_fresh_submission_snapshot() -> None:
    conn = connect(":memory:")
    initial_at = SUBMITTED_AT - timedelta(minutes=20)
    _prepare_live_boundary(conn, captured_at=initial_at)
    submission_snapshot = LivePortfolioSnapshot(
        portfolio_snapshot_id="snap_codex_submit",
        execution_profile_id="codex",
        broker_account_fingerprint="0" * 16,
        captured_at=SUBMITTED_AT - timedelta(minutes=1),
        account_equity=105,
        buying_power=95,
    )
    save_live_portfolio_snapshot(conn, submission_snapshot, _profile())

    outcome = submit_decision(
        conn,
        _record(),
        date(2026, 6, 10),
        execution_mode=ExecutionMode.LIVE,
        execution_profile_id="codex",
        reasoning_run_id=RUN_ID,
        execution_profile=_profile(),
        submission_snapshot_id=submission_snapshot.portfolio_snapshot_id,
        submitted_at=SUBMITTED_AT,
    )

    linked = conn.execute(
        """
        SELECT reasoning_run_id, submission_snapshot_id
        FROM reasoning_run_decisions
        WHERE decision_id = ?
        """,
        (f"{RUN_ID}_dec_001",),
    ).fetchone()
    assert outcome.order_intent_id == f"oi_{RUN_ID}_dec_001"
    assert linked == (RUN_ID, "snap_codex_submit")


@pytest.mark.parametrize("mode", ["missing", "future_only", "valid_and_premature"])
def test_live_regime_binding_uses_only_completed_session(mode: str) -> None:
    conn = connect(":memory:")
    _prepare_live_boundary(conn, captured_at=SUBMITTED_AT)
    if mode != "valid_and_premature":
        conn.execute("DELETE FROM regime_snapshots")
    if mode != "missing":
        conn.execute(
            "INSERT INTO regime_snapshots VALUES (?, ?, ?, ?, ?, ?)",
            ("2026-06-10", "GREEN", "GREEN", 5, "{}", SUBMITTED_AT.isoformat()),
        )
    conn.commit()
    kwargs: dict[str, Any] = dict(
        execution_mode=ExecutionMode.LIVE,
        execution_profile_id="codex",
        reasoning_run_id=RUN_ID,
        execution_profile=_profile(),
        submission_snapshot_id="snap_codex",
        submitted_at=SUBMITTED_AT,
    )
    if mode == "valid_and_premature":
        outcome = submit_decision(conn, _record(), date(2026, 6, 10), **kwargs)
        assert outcome.order_intent_id
        raw = conn.execute("SELECT evaluation_json FROM policy_evaluations").fetchone()[0]
        assert '"regime_snapshot_id":"2026-06-09"' in raw
    else:
        with pytest.raises(ValueError, match="regime_missing"):
            submit_decision(conn, _record(), date(2026, 6, 10), **kwargs)
        assert conn.execute("SELECT COUNT(*) FROM order_intents").fetchone()[0] == 0
    conn.close()


def test_complete_live_real_parser_does_not_require_date_and_closes_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.reason import run
    from app.storage.records import get_reasoning_run

    source = tmp_path / "source.db"
    conn = connect(source)
    _prepare_live_boundary(conn, captured_at=SUBMITTED_AT)
    prepared = get_reasoning_run(conn, RUN_ID)
    assert prepared
    completed = prepared.model_copy(
        update={
            "result": ReasoningRunResult.NO_ACTION,
            "completed_at": SUBMITTED_AT,
            "public_summary": "No action after review.",
        }
    )
    path = tmp_path / "complete.json"
    path.write_text(completed.model_dump_json(), encoding="utf-8")
    conn.close()
    opened: list[sqlite3.Connection] = []

    def tracked(path: str) -> sqlite3.Connection:
        db = connect(path)
        opened.append(db)
        return db

    monkeypatch.setattr(run, "connect", tracked)
    monkeypatch.setattr(
        "sys.argv", ["reason", "--db", str(source), "complete-live", "--in", str(path)]
    )
    run.main()
    assert '"result": "NO_ACTION"' in capsys.readouterr().out
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        opened[0].execute("SELECT 1")
