import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from app.public.activity import history, runtime_status
from app.public.database import open_readonly
from app.public.publication import publish
from app.storage.database import connect
from app.storage.runtime import claim, heartbeat
from tests.reason.test_runtime import NOW, paper_run


def test_heartbeat_publication_updates_one_run_without_decision_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, public = tmp_path / "source.db", tmp_path / "public.db"
    conn = connect(source)
    run = paper_run(conn, tmp_path)
    attempt = claim(conn, run.run_id, "model", NOW)
    paper_run(conn, tmp_path, run_id="newer", prepared_at=NOW + timedelta(seconds=1))
    publish(source, public)
    with open_readonly(public) as reader:
        status = runtime_status(reader, "paper", NOW)
        assert status["latest_run"]["status"] == "prepared"
        assert status["active_run"]["status"] == "running"
        assert history(reader, "paper", limit=1)["next_cursor"]
    from app.schemas.decision_record import InvestmentDecisionRecord

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("heartbeat replayed decision history")

    monkeypatch.setattr(InvestmentDecisionRecord, "model_validate_json", forbidden)
    heartbeat(conn, attempt.attempt_id, attempt.fence, NOW + timedelta(seconds=2))
    assert publish(source, public) == {"inserted": 0, "updated": 0, "withdrawn": 0}
    with open_readonly(public) as reader:
        status = runtime_status(reader, "paper", NOW + timedelta(seconds=3))
        assert (
            status["active_run"]["latest_attempt"]["heartbeat_at"]
            == (NOW + timedelta(seconds=2)).isoformat()
        )
        assert (
            runtime_status(reader, "paper", NOW + timedelta(hours=1))["active_run"]["status"]
            == "stale"
        )
        rows = history(reader, "paper")
        assert rows["total"] == 2
        assert "research" not in json.dumps(rows)
    conn.close()


def test_run_filter_retry_detail_and_private_identity_never_leak(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from app.public.server import create_public_app
    from app.reason.worker import execute_attempt
    from app.schemas.decision_record import InvestmentDecisionRecord
    from app.schemas.runtime import AuthoredOutput
    from tests.fixtures.decision_records import valid_decision_record_data

    source, public = tmp_path / "source.db", tmp_path / "public.db"
    conn = connect(source)
    run = paper_run(conn, tmp_path)

    def author(prompt: str, **kwargs: object) -> AuthoredOutput:
        namespace = prompt.split("Decision namespace: ")[1].splitlines()[0]
        return AuthoredOutput(
            decisions=[
                InvestmentDecisionRecord.model_validate(
                    {
                        **valid_decision_record_data(),
                        "decision_id": namespace + str(index),
                    }
                )
                for index in range(2)
            ],
            public_summary="Reviewed two candidates.",
        )

    from app.reason.codex_runner import RunnerFailure

    def failed_author(prompt: str, **kwargs: object) -> AuthoredOutput:
        raise RunnerFailure("runner_failed")

    failed = execute_attempt(
        conn,
        run.run_id,
        "first-model",
        log_root=tmp_path / "logs",
        runner=failed_author,
        clock=lambda: NOW,
    )
    assert failed.status == "failed"
    attempt = execute_attempt(
        conn,
        run.run_id,
        "actual-model",
        log_root=tmp_path / "logs",
        runner=author,
        clock=lambda: NOW,
        retry=True,
    )
    assert attempt.status == "completed"
    publish(source, public)
    client = TestClient(create_public_app(public))
    runs = client.get("/api/public/v2/portfolios/paper/activity").json()
    public_id = runs["items"][0]["public_id"]
    detail = client.get(f"/api/public/v2/portfolios/paper/activity/{public_id}")
    assert [item["status"] for item in detail.json()["attempts"]] == ["completed", "failed"]
    assert detail.json()["attempts"][0]["requested_model"] == "actual-model"
    assert client.get(f"/api/public/v2/portfolios/live/activity/{public_id}").status_code == 404
    params = {"portfolio_id": "paper", "run_id": public_id, "limit": 1}
    page = client.get("/api/public/v2/decisions", params=params).json()
    assert page["total"] == 2 and page["items"][0]["public_run_id"] == public_id
    assert (
        client.get(
            "/api/public/v2/decisions",
            params={**params, "run_id": "run_" + "0" * 32, "cursor": page["next_cursor"]},
        ).status_code
        == 422
    )
    for secret in (attempt.attempt_id, run.run_id, str(tmp_path), "intake.md"):
        assert secret not in detail.text
    conn.close()


def test_changed_skipped_occurrence_and_profile_withdrawal_are_reconciled(tmp_path: Path) -> None:
    from app.schemas.runtime import ScheduleRevision, SchedulerObservation
    from app.storage.schedules import observe, record_due, save_schedule

    source, public = tmp_path / "source.db", tmp_path / "public.db"
    conn = connect(source)
    schedule = ScheduleRevision(
        schedule_id="close",
        revision=1,
        mode="paper",
        account_id="paper",
        enabled=True,
        schedule_mode="scheduled",
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
    conn.execute(
        "UPDATE schedule_occurrences SET status='skipped', reason='overlap' WHERE occurrence_id=?",
        (occurrence,),
    )
    conn.commit()
    publish(source, public)
    with open_readonly(public) as reader:
        assert history(reader, "paper")["items"][0]["reason"] == "overlap"
    conn.execute(
        "UPDATE schedule_occurrences SET status='waiting', reason=NULL WHERE occurrence_id=?",
        (occurrence,),
    )
    conn.commit()
    publish(source, public)
    with open_readonly(public) as reader:
        assert history(reader, "paper")["total"] == 0
    from tests.reason.test_live_submit import SUBMITTED_AT, _prepare_live_boundary

    _prepare_live_boundary(conn, captured_at=SUBMITTED_AT)
    publish(source, public, live_profiles=("codex",))
    with open_readonly(public) as reader:
        legacy_id = history(reader, "live")["items"][0]["public_id"]
    publish(source, public, live_profiles=())
    with open_readonly(public) as reader:
        assert history(reader, "live")["total"] == 0
        assert not reader.execute(
            "SELECT 1 FROM public_activity WHERE public_id=?", (legacy_id,)
        ).fetchone()
    conn.close()


def test_source_counter_regression_rebuilds_and_keeps_stable_public_ids(tmp_path: Path) -> None:
    from app.public.queries import feed
    from tests.public.test_public_v2 import seed

    source, public = tmp_path / "source.db", tmp_path / "public.db"
    seed(source, 1)
    publish(source, public)
    with open_readonly(public) as reader:
        public_id = feed(reader, portfolio_id="paper")["items"][0]["public_id"]
    conn = connect(source)
    conn.execute(
        "UPDATE decision_records SET record_json=json_set(record_json, "
        "'$.public_summary', 'Restored source')"
    )
    conn.execute("UPDATE publication_changes SET details=0, performance=0, activity=0")
    conn.commit()
    publish(source, public)
    with open_readonly(public) as reader:
        item = feed(reader, portfolio_id="paper")["items"][0]
        assert item["public_id"] == public_id and item["public_summary"] == "Restored source"
    conn.close()


def test_accounting_clock_refreshes_performance_without_replaying_decisions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, date, datetime

    from app.paper.broker import settle
    from app.prices.cache import upsert_daily_prices
    from app.public import publication
    from app.schemas.decision_record import InvestmentDecisionRecord
    from tests.paper.test_paper import _bar, _intent

    source, public = tmp_path / "source.db", tmp_path / "public.db"
    conn = connect(source)
    _intent(conn, "clock", "BUY", 0.1, date(2026, 6, 9))
    upsert_daily_prices(conn, [_bar("NVDA", date(2026, 6, 10), 100)])
    assert settle(conn) == (1, 0)
    conn.close()

    class Clock(datetime):
        current = datetime(2026, 6, 10, 19, 59, tzinfo=UTC)

        @classmethod
        def now(cls, tz: Any = None) -> "Clock":
            return cls.fromisoformat(cls.current.isoformat())

    monkeypatch.setattr(publication, "datetime", Clock)
    publish(source, public)
    with open_readonly(public) as reader:
        before_portfolio = json.loads(
            reader.execute(
                "SELECT content FROM public_portfolios WHERE portfolio_id='paper'"
            ).fetchone()[0]
        )
        assert before_portfolio["equity"] is None
        before = reader.execute("SELECT revision FROM publication_meta").fetchone()[0]

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("clock transition replayed immutable decisions")

    monkeypatch.setattr(InvestmentDecisionRecord, "model_validate_json", forbidden)
    Clock.current = datetime(2026, 6, 10, 20, 0, tzinfo=UTC)
    publish(source, public)
    with open_readonly(public) as reader:
        after_portfolio = json.loads(
            reader.execute(
                "SELECT content FROM public_portfolios WHERE portfolio_id='paper'"
            ).fetchone()[0]
        )
        assert after_portfolio["equity"] == "5000.00"
        assert after_portfolio["positions"][0]["price_quality"] == "current"
        assert reader.execute("SELECT revision FROM publication_meta").fetchone()[0] == before
        assert (
            json.loads(reader.execute("SELECT content FROM publication_checkpoint").fetchone()[0])[
                "accounting_clock"
            ][0]
            == "2026-06-10"
        )


def test_watch_rejects_missing_or_same_source_before_initialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.public.publication import main

    source, public = tmp_path / "source.db", tmp_path / "public.db"
    monkeypatch.setattr(
        "sys.argv", ["publish", "--source", str(source), "--public-db", str(public), "--watch", "1"]
    )
    with pytest.raises(FileNotFoundError):
        main()
    assert not source.exists() and not public.exists()
    source.write_bytes(b"not a database")
    monkeypatch.setattr(
        "sys.argv", ["publish", "--source", str(source), "--public-db", str(source), "--watch", "1"]
    )
    with pytest.raises(ValueError, match="separate"):
        main()
    assert source.read_bytes() == b"not a database"


def test_wrapping_legacy_run_keeps_shared_activity_and_decision_urls(tmp_path: Path) -> None:
    from app.public.queries import feed
    from app.reason.run import submit_decision
    from app.schemas.order_intent import ExecutionMode
    from app.storage.runtime import save_run
    from tests.fixtures.decision_records import valid_decision_record_data
    from tests.reason.test_live_submit import _profile
    from tests.reason.test_runtime import live_run

    source, public = tmp_path / "source.db", tmp_path / "public.db"
    conn = connect(source)
    run = live_run(conn, tmp_path)
    submit_decision(
        conn,
        {**valid_decision_record_data(), "decision_id": "legacy-live_first"},
        NOW.date(),
        execution_mode=ExecutionMode.LIVE,
        execution_profile_id="codex",
        reasoning_run_id="legacy-live",
        submission_snapshot_id="starting",
        execution_profile=_profile(),
        submitted_at=NOW,
    )
    publish(source, public, live_profiles=("codex",))
    with open_readonly(public) as reader:
        legacy_id = history(reader, "live")["items"][0]["public_id"]
        decision = feed(reader, portfolio_id="live")["items"][0]
        assert decision["public_run_id"] == legacy_id
    save_run(conn, run)
    publish(source, public, live_profiles=("codex",))
    with open_readonly(public) as reader:
        assert history(reader, "live")["total"] == 1
        assert history(reader, "live")["items"][0]["public_id"] == legacy_id
        assert feed(reader, portfolio_id="live")["items"][0]["public_run_id"] == legacy_id
    publish(source, public, live_profiles=("codex",), rebuild=True)
    with open_readonly(public) as reader:
        assert history(reader, "live")["items"][0]["public_id"] == legacy_id
    conn.close()
