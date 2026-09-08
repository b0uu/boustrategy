import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier

import pytest

from app.reason import scheduler
from app.reason.run import PreparationResult
from app.schemas.runtime import AuthoredOutput, ScheduleRevision, SchedulerObservation
from app.storage.database import connect
from app.storage.schedules import observe, record_due, save_schedule
from tests.reason.test_runtime import NOW, paper_run


def test_scheduled_restart_reuses_prepared_occurrence_and_duplicate_workers_do_not_rerun(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.db"
    conn = connect(source, wal=True)
    schedule = ScheduleRevision(
        schedule_id="close",
        revision=1,
        mode="paper",
        account_id="paper",
        schedule_mode="scheduled",
        enabled=True,
        configured_at=NOW - timedelta(hours=2),
    )
    save_schedule(conn, schedule)
    observe(
        conn,
        SchedulerObservation(
            schedule_id="close",
            revision=1,
            observed_at=NOW,
            observer="worker",
            configured=True,
            enabled=True,
        ),
    )
    occurrence = record_due(conn, "close", NOW)[0]
    prepared = paper_run(conn, tmp_path, origin="scheduled", occurrence_id=occurrence)
    receipt = PreparationResult(
        session_date=NOW.date(),
        prepared_at=NOW,
        digest_path="digest.md",
        completed_digest_runs=["digest"],
        refreshed_price_bars={},
        refreshed_calendar_events={},
        fills_created=0,
        intents_awaiting_price=0,
        trigger_counts={},
        regime="GREEN",
        raw_regime="GREEN",
        regime_score=5,
        bundle_path=prepared.intake_path,
    )
    receipt_path = tmp_path / "preparation.json"
    receipt_path.write_text(receipt.model_dump_json(), encoding="utf-8")
    conn.close()
    monkeypatch.setattr(scheduler, "_completed_digest_runs", lambda *args: ["digest"])
    barrier = Barrier(2)

    def synchronized_due(*args: object) -> list[str]:
        with connect(source) as db:
            result = record_due(db, "close", NOW)
        barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(scheduler, "record_due", synchronized_due)
    calls: list[str] = []

    def author(prompt: str, **kwargs: object) -> AuthoredOutput:
        calls.append(prompt)
        return AuthoredOutput(public_summary="No action after review.")

    def worker(index: int) -> list[dict[str, object]]:
        db = connect(source)
        try:
            return scheduler.execute_due(
                db,
                "close",
                "model",
                NOW,
                output_dir=tmp_path / "intakes",
                log_root=tmp_path / "logs",
                digest_dir=tmp_path,
                paper_intake=receipt_path,
                runner=author,
                clock=lambda: NOW,
            )
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(worker, range(2)))
    assert len(calls) == 1
    assert any(item["status"] == "no_action" for rows in outcomes for item in rows)
    conn = connect(source)
    assert conn.execute("SELECT COUNT(*) FROM runtime_runs").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM runtime_attempts").fetchone()[0] == 1
    assert (
        hashlib.sha256(Path(prepared.intake_path).read_bytes()).hexdigest()
        == prepared.intake_sha256
    )
    conn.close()


def test_missing_dependency_keeps_private_diagnostics_then_grace_skips(tmp_path: Path) -> None:
    conn = connect(tmp_path / "source.db")
    schedule = ScheduleRevision(
        schedule_id="private-close",
        revision=1,
        mode="paper",
        account_id="paper",
        schedule_mode="scheduled",
        enabled=True,
        configured_at=NOW - timedelta(hours=2),
    )
    save_schedule(conn, schedule)
    result = scheduler.execute_due(
        conn,
        schedule.schedule_id,
        "model",
        NOW,
        output_dir=tmp_path / "intakes",
        log_root=tmp_path / "logs",
        digest_dir=tmp_path / "missing",
    )
    assert result == [{"status": "waiting", "reason": "dependency_missing"}]
    logs = list((tmp_path / "logs").rglob("dependency.txt"))
    assert len(logs) == 1 and "missing same-day digest" in logs[0].read_text(encoding="utf-8")
    late = NOW + timedelta(hours=1)
    assert (
        scheduler.execute_due(
            conn,
            schedule.schedule_id,
            "model",
            late,
            output_dir=tmp_path / "intakes",
            log_root=tmp_path / "logs",
            digest_dir=tmp_path,
        )
        == []
    )
    assert conn.execute("SELECT status, reason FROM schedule_occurrences").fetchone() == (
        "skipped",
        "grace_expired",
    )
    assert conn.execute("SELECT COUNT(*) FROM runtime_attempts").fetchone()[0] == 0
    conn.close()


def test_grace_window_crossing_et_midnight_skips_instead_of_crashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "midnight.db"
    conn = connect(source)
    schedule = ScheduleRevision(
        schedule_id="midnight-close",
        revision=1,
        mode="paper",
        account_id="paper",
        schedule_mode="scheduled",
        enabled=True,
        configured_at=NOW - timedelta(hours=2),
        grace_seconds=8 * 3600,
    )
    save_schedule(conn, schedule)
    prepared = paper_run(conn, tmp_path, origin="manual")
    receipt = PreparationResult(
        session_date=NOW.date(),
        prepared_at=NOW,
        digest_path="digest.md",
        completed_digest_runs=["digest"],
        refreshed_price_bars={},
        refreshed_calendar_events={},
        fills_created=0,
        intents_awaiting_price=0,
        trigger_counts={},
        regime="GREEN",
        raw_regime="GREEN",
        regime_score=5,
        bundle_path=prepared.intake_path,
    )
    receipt_path = tmp_path / "midnight-preparation.json"
    receipt_path.write_text(receipt.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(scheduler, "_completed_digest_runs", lambda *args: ["digest"])

    late = NOW + timedelta(hours=7)
    result = scheduler.execute_due(
        conn,
        schedule.schedule_id,
        "model",
        late,
        output_dir=tmp_path / "midnight-intakes",
        log_root=tmp_path / "midnight-logs",
        digest_dir=tmp_path,
        paper_intake=receipt_path,
    )

    assert result == []
    assert conn.execute(
        "SELECT session_date, status, reason FROM schedule_occurrences"
    ).fetchone() == ("2026-06-10", "skipped", "grace_expired")
    assert conn.execute("SELECT COUNT(*) FROM runtime_attempts").fetchone()[0] == 0
    conn.close()

    same_day_conn = connect(tmp_path / "same-day.db")
    same_day_schedule = schedule.model_copy(update={"schedule_id": "same-day-close"})
    save_schedule(same_day_conn, same_day_schedule)
    same_day = NOW + timedelta(hours=5)
    same_day_result = scheduler.execute_due(
        same_day_conn,
        same_day_schedule.schedule_id,
        "model",
        same_day,
        output_dir=tmp_path / "same-day-intakes",
        log_root=tmp_path / "same-day-logs",
        digest_dir=tmp_path / "missing",
    )
    assert same_day_result == [{"status": "waiting", "reason": "dependency_missing"}]
    assert same_day_conn.execute("SELECT status, reason FROM schedule_occurrences").fetchone() == (
        "waiting",
        "dependency_missing",
    )
    same_day_conn.close()
