import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.broker.executor import (
    MAX_ATTEMPTS_PER_INTENT,
    RECOVERY_WARNING,
    ExecutionReport,
    execute_pending,
    execution_prompt,
    pending_live_intents,
    verify_report,
)
from app.broker.session import BrokerSessionFailure
from app.orders.create_order_intent import create_order_intent
from app.policy.decision_policy import PolicyResult
from app.schemas.broker_execution import BrokerExecutionRecord
from app.schemas.live_execution import ExecutionProfile
from app.schemas.order_intent import ExecutionMode, OrderIntent
from app.storage.database import connect
from app.storage.records import (
    save_broker_execution_record,
    save_decision_record,
    save_execution_packet,
    save_order_intent,
)
from tests.fixtures.decision_records import valid_decision_record
from tests.fixtures.live_execution import live_execution_packet


def _profile(enabled: bool = True) -> ExecutionProfile:
    return ExecutionProfile(
        execution_profile_id="codex",
        agent_provider="CODEX",
        account_alias="codex-agentic",
        broker_account_fingerprint="f00dfeedcafe0001",
        enabled=enabled,
        max_order_notional=20,
        max_quote_age_seconds=60,
        max_spread_bps=50,
    )


def _live_intent(db_path: Path, created_at: datetime) -> OrderIntent:
    conn = connect(db_path)
    record = valid_decision_record()
    intent = create_order_intent(
        record,
        PolicyResult(approved=True),
        execution_mode=ExecutionMode.LIVE,
        execution_profile_id="codex",
        created_at=created_at,
    )
    save_decision_record(conn, record)
    save_order_intent(conn, intent)
    conn.close()
    return intent


def _session_returning(payload: dict[str, Any], seen: dict[str, Any]) -> Any:
    def session(prompt: str, *, schema: Any, **kwargs: Any) -> Any:
        seen["prompt"] = prompt
        seen["schema"] = schema
        seen["kwargs"] = kwargs
        return schema.model_validate(payload)

    return session


def test_pending_intents_skip_executed_and_out_of_session_ones(tmp_path: Path) -> None:
    db_path = tmp_path / "boustrategy.db"
    now = datetime(2026, 9, 10, 13, 32, tzinfo=UTC)
    intent = _live_intent(db_path, now - timedelta(hours=15))
    conn = connect(db_path)

    fresh = pending_live_intents(conn, _profile(), now=now)
    save_execution_packet(conn, live_execution_packet(intent))
    save_broker_execution_record(
        conn,
        BrokerExecutionRecord(
            broker_execution_record_id="ber_1",
            order_intent_id=intent.order_intent_id,
            execution_packet_id=f"ep_codex_{intent.order_intent_id}",
            execution_profile_id="codex",
            account_alias="codex-agentic",
            ticker=intent.ticker,
            side=intent.side,
            order_type=intent.order_type,
            requested_notional=12.0,
            limit_price=200.0,
            submitted_at=datetime(2026, 8, 26, 14, 0, 30, tzinfo=UTC),
            status="SUBMITTED",
            broker_order_id="rh-1",
            execution_price=0.0,
        ),
    )
    after_record = pending_live_intents(conn, _profile(), now=now)
    too_old = pending_live_intents(conn, _profile(), now=now + timedelta(days=3))

    assert [item.order_intent_id for item in fresh] == [intent.order_intent_id]
    assert after_record == [] and too_old == []
    conn.close()


def test_execute_pending_runs_one_session_per_intent_and_verifies_ledger(tmp_path: Path) -> None:
    db_path = tmp_path / "boustrategy.db"
    now = datetime(2026, 9, 10, 13, 32, tzinfo=UTC)
    intent = _live_intent(db_path, now - timedelta(hours=15))
    seen: dict[str, Any] = {}
    payload = {
        "order_intent_id": intent.order_intent_id,
        "outcome": "submitted",
        "execution_packet_id": "ep_missing",
        "broker_execution_record_id": "ber_missing",
        "broker_order_id": "rh-9",
        "notes": "placed but never recorded",
    }

    results = execute_pending(
        db_path,
        _profile(),
        now=now,
        session=_session_returning(payload, seen),
        codex_home=tmp_path,
        repo_root=tmp_path,
        log_dir=tmp_path / "broker-logs",
    )

    assert len(results) == 1
    assert results[0]["problems"] == ["unrecorded_submission", "reported_packet_missing"]
    assert seen["kwargs"]["sandbox"] == "workspace-write"
    assert seen["schema"] is ExecutionReport
    assert intent.order_intent_id in seen["prompt"]
    assert "docs/execution/EXECUTOR.md" in seen["prompt"]
    assert "ref_id" in seen["prompt"] and "Never run git" in seen["prompt"]
    ledger = (tmp_path / "broker-logs" / "executions.jsonl").read_text(encoding="utf-8")
    assert json.loads(ledger.splitlines()[0])["report"]["broker_order_id"] == "rh-9"


def test_execute_pending_reports_session_failure_and_clean_non_placement(tmp_path: Path) -> None:
    db_path = tmp_path / "boustrategy.db"
    now = datetime(2026, 9, 10, 13, 32, tzinfo=UTC)
    intent = _live_intent(db_path, now - timedelta(hours=1))

    def failing(prompt: str, **kwargs: Any) -> Any:
        raise BrokerSessionFailure("session_timeout")

    failed = execute_pending(
        db_path, _profile(), now=now, session=failing, codex_home=tmp_path, log_dir=tmp_path / "a"
    )
    clean = execute_pending(
        db_path,
        _profile(),
        now=now,
        session=_session_returning(
            {"order_intent_id": intent.order_intent_id, "outcome": "blocked", "notes": "closed"},
            {},
        ),
        codex_home=tmp_path,
        log_dir=tmp_path / "b",
    )

    assert failed[0]["problems"] == ["session_failed"]
    assert failed[0]["session_failure"] == "session_timeout"
    assert clean[0]["problems"] == []


def test_verify_report_flags_intent_mismatch_and_unexpected_record(tmp_path: Path) -> None:
    db_path = tmp_path / "boustrategy.db"
    now = datetime(2026, 9, 10, 13, 32, tzinfo=UTC)
    intent = _live_intent(db_path, now)
    conn = connect(db_path)

    mismatch = verify_report(
        conn, intent, ExecutionReport(order_intent_id="other", outcome="not_placed")
    )

    assert mismatch == ["report_intent_mismatch"]
    assert "maximum order notional $20.00" in execution_prompt(intent, _profile())
    conn.close()


def test_pending_intents_keep_an_overnight_intent_but_drop_a_day_old_one(tmp_path: Path) -> None:
    db_path = tmp_path / "boustrategy.db"
    # Thursday 09:40 ET; Wednesday's close is the staleness boundary.
    now = datetime(2026, 9, 10, 13, 40, tzinfo=UTC)
    overnight = _live_intent(db_path, datetime(2026, 9, 9, 22, 15, tzinfo=UTC))
    conn = connect(db_path)

    assert [item.order_intent_id for item in pending_live_intents(conn, _profile(), now=now)] == [
        overnight.order_intent_id
    ]
    # The same intent one session later is anchored to a price nobody checked since.
    friday = datetime(2026, 9, 11, 13, 40, tzinfo=UTC)
    assert pending_live_intents(conn, _profile(), now=friday) == []
    conn.close()


def test_execution_attempts_back_off_and_stop_at_the_cap(tmp_path: Path) -> None:
    db_path = tmp_path / "boustrategy.db"
    now = datetime(2026, 9, 10, 14, 0, tzinfo=UTC)
    intent = _live_intent(db_path, now - timedelta(minutes=30))
    blocked = {"order_intent_id": intent.order_intent_id, "outcome": "blocked", "notes": "band"}
    sessions = 0

    def counting(prompt: str, *, schema: Any, **kwargs: Any) -> Any:
        nonlocal sessions
        sessions += 1
        return schema.model_validate(blocked)

    outcomes = []
    for minute in range(0, 240, 20):
        outcomes.append(
            execute_pending(
                db_path,
                _profile(),
                now=now + timedelta(minutes=minute),
                session=counting,
                codex_home=tmp_path,
                log_dir=tmp_path / "logs",
            )[0]
        )

    assert sessions == MAX_ATTEMPTS_PER_INTENT
    assert outcomes[-1]["skipped"] == "attempt_cap_reached"
    immediate_retry = execute_pending(
        db_path,
        _profile(),
        now=now + timedelta(minutes=5),
        session=counting,
        codex_home=tmp_path,
        log_dir=tmp_path / "logs",
    )
    assert immediate_retry[0]["skipped"] in {"retry_backoff", "attempt_cap_reached"}
    assert sessions == MAX_ATTEMPTS_PER_INTENT


def test_a_retry_is_told_to_check_broker_history_before_placing_again(tmp_path: Path) -> None:
    db_path = tmp_path / "boustrategy.db"
    now = datetime(2026, 9, 10, 14, 0, tzinfo=UTC)
    intent = _live_intent(db_path, now - timedelta(minutes=30))
    prompts: list[str] = []

    def recording(prompt: str, *, schema: Any, **kwargs: Any) -> Any:
        prompts.append(prompt)
        return schema.model_validate(
            {"order_intent_id": intent.order_intent_id, "outcome": "blocked", "notes": ""}
        )

    for minute in (0, 20):
        execute_pending(
            db_path,
            _profile(),
            now=now + timedelta(minutes=minute),
            session=recording,
            codex_home=tmp_path,
            log_dir=tmp_path / "logs",
        )

    assert not prompts[0].startswith(RECOVERY_WARNING)
    assert prompts[1].startswith(RECOVERY_WARNING)
    assert "get_equity_orders" in prompts[1] and "Placing again would duplicate" in prompts[1]
