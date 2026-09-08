import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.reason.codex_runner import RunnerFailure
from app.reason.worker import execute_attempt
from app.schemas.decision_record import InvestmentDecisionRecord
from app.schemas.runtime import AuthoredOutput, RuntimeRun, ScheduleRevision, SchedulerObservation
from app.storage.database import connect
from app.storage.runtime import (
    LeaseLost,
    claim,
    expire,
    finish,
    get_attempt,
    heartbeat,
    immediate,
    save_run,
)
from app.storage.schedules import observe, planned_preview, preview, record_due, save_schedule
from tests.fixtures.decision_records import valid_decision_record_data

NOW = datetime(2026, 6, 10, 21, 45, tzinfo=UTC)


def paper_run(conn: sqlite3.Connection, folder: Path, **changes: object) -> RuntimeRun:
    path = folder / "intake.md"
    path.write_text("Deliberate intake", encoding="utf-8")
    run = RuntimeRun.model_validate(
        {
            "run_id": "research",
            "mode": "paper",
            "account_id": "paper",
            "session_date": NOW.date(),
            "slot": "close",
            "prepared_at": NOW,
            "intake_path": str(path),
            "intake_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            **changes,
        }
    )
    save_run(conn, run)
    return run


def test_duplicate_claim_fencing_expiry_and_late_completion_across_connections(
    tmp_path: Path,
) -> None:
    path = tmp_path / "source.db"
    conn, other = connect(path), connect(path)
    run = paper_run(conn, tmp_path)
    first = claim(conn, run.run_id, "first-model", NOW, lease_seconds=10)
    with pytest.raises(ValueError, match="overlap"):
        claim(other, run.run_id, "second-model", NOW)
    with immediate(other):
        assert expire(other, NOW + timedelta(seconds=11)) == 1
    second = claim(other, run.run_id, "second-model", NOW + timedelta(seconds=11), retry=True)
    assert second.fence > first.fence
    with pytest.raises(LeaseLost):
        heartbeat(conn, first.attempt_id, first.fence, NOW + timedelta(seconds=12))
    with pytest.raises(LeaseLost):
        finish(conn, first.attempt_id, first.fence, NOW + timedelta(seconds=12), status="no_action")
    assert get_attempt(conn, first.attempt_id).status == "expired"
    finish(other, second.attempt_id, second.fence, NOW + timedelta(seconds=13), status="no_action")
    conn.close()
    other.close()


def test_worker_partial_failure_explicit_retry_preserves_decisions_and_models(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "source.db")
    run = paper_run(conn, tmp_path)

    def first_runner(prompt: str, **kwargs: object) -> AuthoredOutput:
        namespace = prompt.split("Decision namespace: ")[1].splitlines()[0]
        first = InvestmentDecisionRecord.model_validate(
            {**valid_decision_record_data(), "decision_id": namespace + "one"}
        )
        second = first.model_copy(update={"public_summary": "Conflicting immutable record"})
        return AuthoredOutput(decisions=[first, second], public_summary="Two candidates reviewed.")

    failed = execute_attempt(
        conn,
        run.run_id,
        "first-model",
        log_root=tmp_path / "logs",
        runner=first_runner,
        clock=lambda: NOW,
    )
    assert failed.status == "blocked"
    assert conn.execute("SELECT COUNT(*) FROM decision_records").fetchone()[0] == 1
    with pytest.raises(ValueError, match="retry"):
        execute_attempt(
            conn, run.run_id, "second-model", log_root=tmp_path / "logs", clock=lambda: NOW
        )

    def second_runner(prompt: str, **kwargs: object) -> AuthoredOutput:
        namespace = prompt.split("Decision namespace: ")[1].splitlines()[0]
        record = InvestmentDecisionRecord.model_validate(
            {**valid_decision_record_data(), "decision_id": namespace + "two"}
        )
        return AuthoredOutput(decisions=[record], public_summary="One new candidate reviewed.")

    completed = execute_attempt(
        conn,
        run.run_id,
        "second-model",
        log_root=tmp_path / "logs",
        runner=second_runner,
        clock=lambda: NOW + timedelta(seconds=1),
        retry=True,
    )
    assert completed.status == "completed" and completed.attempt_number == 2
    assert conn.execute("SELECT COUNT(*) FROM decision_records").fetchone()[0] == 2
    assert get_attempt(conn, failed.attempt_id).status == "blocked"
    assert conn.execute(
        "SELECT DISTINCT created_at FROM decision_records ORDER BY created_at"
    ).fetchall() == [(NOW.isoformat(),), ((NOW + timedelta(seconds=1)).isoformat(),)]
    assert conn.execute(
        "SELECT a.model FROM decision_records d JOIN runtime_attempts a ON "
        "a.attempt_id=d.runtime_attempt_id ORDER BY d.created_at"
    ).fetchall() == [("first-model",), ("second-model",)]
    conn.close()


def test_worker_records_cleanup_failure_and_finishes_attempt(tmp_path: Path) -> None:
    conn = connect(tmp_path / "source.db")
    run = paper_run(conn, tmp_path)

    def runner(prompt: str, **kwargs: object) -> AuthoredOutput:
        raise RunnerFailure("subprocess_pipe_cleanup_failed")

    failed = execute_attempt(
        conn,
        run.run_id,
        "model",
        log_root=tmp_path / "logs",
        runner=runner,
        clock=lambda: NOW,
    )

    assert failed.status == "failed"
    assert failed.reason == "subprocess_pipe_cleanup_failed"
    assert conn.execute("SELECT attempt_id FROM runtime_leases").fetchone() == (None,)
    conn.close()


def test_inactive_preview_observation_pause_and_revised_waiting_occurrence(tmp_path: Path) -> None:
    conn = connect(tmp_path / "source.db")
    schedule = ScheduleRevision(
        schedule_id="paper-close",
        revision=1,
        mode="paper",
        account_id="paper",
        configured_at=NOW - timedelta(hours=2),
    )
    save_schedule(conn, schedule)
    assert planned_preview(schedule, NOW)["items"]
    assert preview(conn, schedule, NOW)["next_due_at"] is None
    enabled = schedule.model_copy(
        update={"revision": 2, "schedule_mode": "scheduled", "enabled": True}
    )
    save_schedule(conn, enabled)
    observe(
        conn,
        SchedulerObservation(
            schedule_id=enabled.schedule_id,
            revision=2,
            observed_at=NOW,
            observer="windows_task",
            configured=True,
            enabled=False,
            next_run_at=NOW + timedelta(days=1),
        ),
    )
    assert preview(conn, enabled, NOW)["reason"] == "observer_disabled"
    observe(
        conn,
        SchedulerObservation(
            schedule_id=enabled.schedule_id,
            revision=2,
            observed_at=NOW,
            observer="worker",
            configured=True,
            enabled=True,
        ),
    )
    occurrence = record_due(conn, enabled.schedule_id, NOW)[0]
    run = paper_run(conn, tmp_path, origin="scheduled", occurrence_id=occurrence)
    first = claim(conn, run.run_id, "model", NOW)
    paused = enabled.model_copy(update={"revision": 3, "paused": True, "configured_at": NOW})
    save_schedule(conn, paused)
    heartbeat(conn, first.attempt_id, first.fence, NOW + timedelta(seconds=1))
    finish(conn, first.attempt_id, first.fence, NOW + timedelta(seconds=2), status="no_action")
    assert preview(conn, paused, NOW)["reason"] == "paused"
    with pytest.raises(sqlite3.IntegrityError):
        paper_run(conn, tmp_path, run_id="duplicate", origin="scheduled", occurrence_id=occurrence)
    conn.close()


def test_waiting_revision_can_move_due_and_remove_early_close_eligibility(tmp_path: Path) -> None:
    from datetime import date, time

    conn = connect(tmp_path / "source.db")
    now = datetime(2026, 11, 27, 19, 45, tzinfo=UTC)
    schedule = ScheduleRevision(
        schedule_id="paper-close",
        revision=1,
        mode="paper",
        account_id="paper",
        configured_at=now - timedelta(hours=2),
        enabled=True,
        schedule_mode="scheduled",
    )
    save_schedule(conn, schedule)
    observe(
        conn,
        SchedulerObservation(
            schedule_id=schedule.schedule_id,
            revision=1,
            observed_at=now,
            observer="worker",
            configured=True,
            enabled=True,
        ),
    )
    occurrence = record_due(conn, schedule.schedule_id, now)[0]
    moved = schedule.model_copy(
        update={
            "revision": 2,
            "configured_at": now,
            "early_close_due_local": time(15, 0),
        }
    )
    save_schedule(conn, moved)
    row = conn.execute("SELECT revision, due_at, status FROM schedule_occurrences").fetchone()
    assert row == (2, "2026-11-27T15:00:00-05:00", "waiting")
    disabled = moved.model_copy(
        update={
            "revision": 3,
            "configured_at": now,
            "early_close_due_local": None,
        }
    )
    save_schedule(conn, disabled)
    row = conn.execute(
        "SELECT revision, due_at, status, reason FROM schedule_occurrences"
    ).fetchone()
    assert row == (3, "2026-11-27T15:00:00-05:00", "skipped", "schedule_ineligible")
    observe(
        conn,
        SchedulerObservation(
            schedule_id=schedule.schedule_id,
            revision=3,
            observed_at=now,
            observer="worker",
            configured=True,
            enabled=True,
        ),
    )
    run = paper_run(
        conn,
        tmp_path,
        session_date=date(2026, 11, 27),
        prepared_at=now,
        origin="scheduled",
        occurrence_id=occurrence,
    )
    with pytest.raises(ValueError, match="occurrence_not_eligible"):
        claim(conn, run.run_id, "model", now)
    assert record_due(conn, schedule.schedule_id, now) == []
    conn.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"reasoning_run_id": "live-run"},
        {"occurrence_id": "reserved"},
        {"origin": "scheduled"},
        {"origin": "event"},
        {"origin": "manual", "trigger_ids": ["trigger"]},
    ],
)
def test_runtime_scope_rejects_invented_identity(
    tmp_path: Path, changes: dict[str, object]
) -> None:
    conn = connect(tmp_path / "source.db")
    with pytest.raises(ValueError):
        paper_run(conn, tmp_path, **changes)
    assert conn.execute("SELECT COUNT(*) FROM runtime_runs").fetchone()[0] == 0
    conn.close()


def test_assembled_intake_supplies_current_episode_and_orders_review_instants(
    tmp_path: Path,
) -> None:
    import json

    from app.performance.report import holding_episodes
    from app.performance.storage import ingest
    from app.reason.runtime_prepare import assemble_intake
    from app.schemas.public_authoring import ThesisReview
    from app.schemas.reporting import CoverageObservation
    from app.storage.public_records import save_thesis_review
    from tests.performance.test_reporting import position, valuation

    conn = connect(tmp_path / "source.db")
    conn.execute("INSERT INTO paper_positions VALUES ('NVDA',1,100,'2026-06-10','ai')")
    start = valuation(
        "opening",
        10,
        "100",
        mode="paper",
        account_id="paper",
        cash="0",
        positions=[position("1", "100")],
    )
    end = valuation(
        "latest",
        10,
        "100",
        mode="paper",
        account_id="paper",
        cash="0",
        positions=[position("1", "100")],
        occurred_at=NOW - timedelta(minutes=45),
        recorded_at=NOW - timedelta(minutes=45),
    )
    covered = CoverageObservation(
        observation_id="coverage",
        external_event_id="coverage",
        mode="paper",
        account_id="paper",
        occurred_at=end.occurred_at,
        recorded_at=end.recorded_at,
        start_at=start.occurred_at,
        end_at=end.occurred_at,
        external_flows_complete=True,
        activity_complete=True,
    )
    for fact in (start, end, covered):
        ingest(conn, fact)
    conn.commit()
    episode = holding_episodes([start, end], [start, end, covered], [covered])["items"][0][
        "episode_id"
    ]
    for identity, instant, summary in (
        ("older", "2026-06-10T22:10:00+02:00", "OLDER_REVIEW"),
        ("latest", "2026-06-10T20:30:00+00:00", "LATEST_REVIEW"),
        ("future", "2026-06-10T23:00:00+00:00", "FUTURE_REVIEW"),
    ):
        at = datetime.fromisoformat(instant)
        save_thesis_review(
            conn,
            ThesisReview(
                review_id=identity,
                mode="paper",
                account_id="paper",
                episode_id=episode,
                ticker="NVDA",
                reviewed_at=at,
                recorded_at=at,
                author="operator",
                state="under_review",
                summary=summary,
            ),
        )
    conn.commit()
    path = tmp_path / "input.md"
    path.write_text("Supplied research", encoding="utf-8")
    run = RuntimeRun(
        run_id="assembled",
        mode="paper",
        account_id="paper",
        session_date=NOW.date(),
        slot="close",
        prepared_at=NOW,
        intake_path=str(path),
        intake_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    prepared = assemble_intake(conn, run, tmp_path / "out")
    text = Path(prepared.intake_path).read_text(encoding="utf-8")
    assert episode in text and "LATEST_REVIEW" in text
    assert "OLDER_REVIEW" not in text and "FUTURE_REVIEW" not in text
    sections = text.split("# Current observed holding episodes\n\n")[1].split("\n\n", 1)[0]
    assert json.loads(sections)["items"][0]["episode_id"] == episode
    conn.close()


def live_run(conn: sqlite3.Connection, folder: Path) -> RuntimeRun:
    from app.schemas.live_execution import LivePortfolioSnapshot
    from app.schemas.reasoning_run import ReasoningRun
    from app.storage.records import save_live_portfolio_snapshot, save_reasoning_run
    from tests.reason.test_live_submit import _profile

    path = folder / "live-intake.md"
    path.write_text("Deliberate live intake", encoding="utf-8")
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    snapshot = LivePortfolioSnapshot(
        portfolio_snapshot_id="starting",
        execution_profile_id="codex",
        broker_account_fingerprint="0" * 16,
        captured_at=NOW,
        account_equity=100,
        buying_power=100,
    )
    save_live_portfolio_snapshot(conn, snapshot, _profile())
    legacy = ReasoningRun(
        reasoning_run_id="legacy-live",
        session_date=NOW.date(),
        slot="close",
        execution_profile_id="codex",
        model_label="original-model",
        shared_bundle_path=str(path),
        shared_bundle_sha256=checksum,
        portfolio_snapshot_id="starting",
        started_at=NOW,
    )
    save_reasoning_run(conn, legacy)
    conn.execute(
        "INSERT INTO regime_snapshots VALUES "
        "('2026-06-10','GREEN','GREEN',5,'{}','2026-06-10T20:00:00+00:00')"
    )
    conn.commit()
    return RuntimeRun(
        run_id="live-runtime",
        mode="live",
        account_id="0" * 16,
        execution_profile_id="codex",
        session_date=NOW.date(),
        slot="close",
        prepared_at=NOW,
        intake_path=str(path),
        intake_sha256=checksum,
        reasoning_run_id=legacy.reasoning_run_id,
    )


@pytest.mark.parametrize("failure", ["stale", "partial"])
def test_live_attempt_rechecks_snapshot_after_authoring_and_preserves_failed_retry(
    tmp_path: Path,
    failure: str,
) -> None:
    from typing import Any

    from app.schemas.live_execution import LivePortfolioSnapshot
    from app.storage.records import get_reasoning_run, save_live_portfolio_snapshot
    from tests.reason.test_live_submit import _profile

    conn = connect(tmp_path / "source.db")
    run = live_run(conn, tmp_path)
    save_run(conn, run)
    current = NOW

    def author(prompt: str, **kwargs: Any) -> AuthoredOutput:
        nonlocal current
        namespace = prompt.split("Decision namespace: ")[1].splitlines()[0]
        record = InvestmentDecisionRecord.model_validate(
            {**valid_decision_record_data(), "decision_id": namespace + "one"}
        )
        if failure == "stale":
            for _ in range(12):
                current += timedelta(seconds=30)
                kwargs["pulse"]()
            return AuthoredOutput(decisions=[record], public_summary="Candidate reviewed.")
        conflict = record.model_copy(update={"public_summary": "Conflicting immutable record"})
        return AuthoredOutput(decisions=[record, conflict], public_summary="Two outputs.")

    first = execute_attempt(
        conn,
        run.run_id,
        "first-model",
        profile=_profile(),
        runner=author,
        clock=lambda: current,
        log_root=tmp_path / "logs",
    )
    assert first.status == "blocked"
    assert first.reason == ("snapshot_stale" if failure == "stale" else "submission_blocked")
    assert conn.execute("SELECT COUNT(*) FROM order_intents").fetchone()[0] == (
        0 if failure == "stale" else 1
    )
    failed_legacy = get_reasoning_run(conn, run.reasoning_run_id or "")
    assert failed_legacy and failed_legacy.result == "FAILED"
    current += timedelta(seconds=1)
    fresh = LivePortfolioSnapshot(
        portfolio_snapshot_id="fresh",
        execution_profile_id="codex",
        broker_account_fingerprint="0" * 16,
        captured_at=current,
        account_equity=100,
        buying_power=100,
    )
    save_live_portfolio_snapshot(conn, fresh, _profile())

    def retry_author(prompt: str, **kwargs: object) -> AuthoredOutput:
        namespace = prompt.split("Decision namespace: ")[1].splitlines()[0]
        record = InvestmentDecisionRecord.model_validate(
            {**valid_decision_record_data(), "decision_id": namespace + "retry"}
        )
        return AuthoredOutput(decisions=[record], public_summary="Fresh snapshot review.")

    retried = execute_attempt(
        conn,
        run.run_id,
        "retry-model",
        profile=_profile(),
        runner=retry_author,
        retry=True,
        clock=lambda: current,
        log_root=tmp_path / "logs",
    )
    assert retried.status == "completed" and retried.attempt_number == 2
    assert get_reasoning_run(conn, run.reasoning_run_id or "") == failed_legacy
    assert get_attempt(conn, first.attempt_id).status == "blocked"
    assert conn.execute("SELECT COUNT(*) FROM decision_records").fetchone()[0] == (
        1 if failure == "stale" else 2
    )
    assert conn.execute(
        "SELECT a.model,l.submission_snapshot_id FROM decision_records d "
        "JOIN runtime_attempts a ON a.attempt_id=d.runtime_attempt_id "
        "JOIN reasoning_run_decisions l USING(decision_id) WHERE a.attempt_id=?",
        (retried.attempt_id,),
    ).fetchone() == ("retry-model", "fresh")
    conn.close()


def test_live_assembly_rejects_a_changed_prepared_bundle(tmp_path: Path) -> None:
    from app.reason.runtime_prepare import assemble_intake
    from tests.reason.test_live_submit import _profile

    conn = connect(tmp_path / "source.db")
    run = live_run(conn, tmp_path)
    Path(run.intake_path).write_text("Changed after preparation", encoding="utf-8")
    changed = run.model_copy(
        update={"intake_sha256": hashlib.sha256(Path(run.intake_path).read_bytes()).hexdigest()}
    )
    with pytest.raises(ValueError, match="bundle identity changed"):
        assemble_intake(conn, changed, tmp_path / "out", _profile())
    assert conn.execute("SELECT COUNT(*) FROM runtime_runs").fetchone()[0] == 0
    conn.close()
