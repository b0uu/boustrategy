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
from app.schemas.decision_record import InvestmentDecisionRecord
from app.schemas.live_execution import ExecutionProfile
from app.schemas.order_intent import ExecutionMode, OrderIntent
from app.storage.database import connect
from app.storage.records import (
    save_broker_execution_record,
    save_decision_record,
    save_execution_packet,
    save_order_intent,
)
from tests.fixtures.decision_records import valid_decision_record, valid_decision_record_data
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


def _swap(db_path: Path, now: datetime) -> OrderIntent:
    """A sale from an earlier session, paired with a buy decided today."""
    conn = connect(db_path)
    sale = InvestmentDecisionRecord.model_validate(
        {
            **valid_decision_record_data(),
            "decision_id": "dec_sale",
            "ticker": "MU",
            "decision": "SELL",
            "proposed_target_weight": 0.0,
            "final_target_weight": 0.0,
        }
    )
    save_decision_record(conn, sale)
    save_order_intent(
        conn,
        create_order_intent(
            sale,
            PolicyResult(approved=True),
            execution_mode=ExecutionMode.LIVE,
            execution_profile_id="codex",
            created_at=now - timedelta(days=1),
        ),
    )
    conn.commit()
    conn.close()
    buy = _live_intent(db_path, now - timedelta(hours=1))
    conn = connect(db_path)
    conn.execute(
        "INSERT INTO swap_pairs VALUES (?, 'dec_sale', ?)", (buy.decision_id, now.isoformat())
    )
    conn.commit()
    conn.close()
    return buy


def _sale_status(db_path: Path, status: str, at: datetime) -> None:
    conn = connect(db_path)
    intent_id = conn.execute(
        "SELECT order_intent_id FROM order_intents WHERE decision_id='dec_sale'"
    ).fetchone()[0]
    conn.execute(
        "INSERT OR IGNORE INTO broker_execution_records (broker_execution_record_id, "
        "order_intent_id, execution_packet_id, execution_profile_id, account_alias, "
        "submitted_at, ticker, side, status, broker_order_id, record_json) "
        "VALUES ('ber_sale', ?, 'ep_sale', 'codex', 'codex-agentic', ?, 'MU', 'SELL', "
        "'SUBMITTED', 'rh-1', '{}')",
        (intent_id, at.isoformat()),
    )
    conn.execute(
        "INSERT INTO broker_execution_events (broker_event_id, broker_execution_record_id, "
        "order_intent_id, execution_packet_id, execution_profile_id, status, occurred_at, "
        "detail, event_json) VALUES (?, 'ber_sale', ?, 'ep_sale', 'codex', ?, ?, '', '{}')",
        (f"bev_sale_{status}", intent_id, status, at.isoformat()),
    )
    conn.commit()
    conn.close()


def test_a_swap_buy_waits_for_its_sale_to_fill(tmp_path: Path) -> None:
    db_path = tmp_path / "boustrategy.db"
    now = datetime(2026, 9, 10, 15, 32, tzinfo=UTC)
    buy = _swap(db_path, now)
    seen: dict[str, Any] = {}
    payload = {"order_intent_id": buy.order_intent_id, "outcome": "not_placed", "notes": "x"}

    def tick() -> list[dict[str, Any]]:
        return execute_pending(
            db_path,
            _profile(),
            now=now,
            session=_session_returning(payload, seen),
            codex_home=tmp_path,
            repo_root=tmp_path,
            log_dir=tmp_path / "broker-logs",
        )

    unsold = tick()
    _sale_status(db_path, "SUBMITTED", now - timedelta(minutes=5))
    submitted = tick()
    _sale_status(db_path, "FILLED", now - timedelta(minutes=4))
    filled = tick()

    assert [unsold[0]["skipped"], submitted[0]["skipped"]] == ["awaiting_swap_sale"] * 2
    assert "skipped" not in filled[0] and buy.order_intent_id in seen["prompt"]


def test_a_swap_buy_is_never_sent_after_its_sale_fails(tmp_path: Path) -> None:
    db_path = tmp_path / "boustrategy.db"
    now = datetime(2026, 9, 10, 15, 32, tzinfo=UTC)
    buy = _swap(db_path, now)
    _sale_status(db_path, "FAILED", now - timedelta(minutes=5))
    seen: dict[str, Any] = {}

    results = execute_pending(
        db_path,
        _profile(),
        now=now,
        session=_session_returning({"order_intent_id": buy.order_intent_id}, seen),
        codex_home=tmp_path,
        repo_root=tmp_path,
        log_dir=tmp_path / "broker-logs",
    )

    assert results == [{"order_intent_id": buy.order_intent_id, "skipped": "swap_sell_failed"}]
    assert seen == {}


def test_sales_go_first_and_only_buys_are_paced(tmp_path: Path) -> None:
    db_path = tmp_path / "boustrategy.db"
    now = datetime(2026, 9, 10, 15, 32, tzinfo=UTC)
    conn = connect(db_path)
    for index, action in enumerate(["BUY", "BUY", "BUY", "SELL", "SELL", "SELL"]):
        record = InvestmentDecisionRecord.model_validate(
            {
                **valid_decision_record_data(),
                "decision_id": f"dec_{index}",
                "decision": action,
                **(
                    {"proposed_target_weight": 0.0, "final_target_weight": 0.0}
                    if action == "SELL"
                    else {}
                ),
            }
        )
        save_decision_record(conn, record)
        save_order_intent(
            conn,
            create_order_intent(
                record,
                PolicyResult(approved=True),
                execution_mode=ExecutionMode.LIVE,
                execution_profile_id="codex",
                created_at=now - timedelta(minutes=30 - index),
            ),
        )
    conn.commit()
    conn.close()
    sides: list[str] = []

    def session(prompt: str, *, schema: Any, **kwargs: Any) -> Any:
        sides.append("SELL" if "(SELL" in prompt else "BUY")
        return schema.model_validate(
            {
                "order_intent_id": prompt.split("order intent: ")[1].split(" ")[0],
                "outcome": "not_placed",
            }
        )

    execute_pending(
        db_path,
        _profile(),
        now=now,
        session=session,
        codex_home=tmp_path,
        repo_root=tmp_path,
        log_dir=tmp_path / "broker-logs",
    )

    assert sides == ["SELL", "SELL", "SELL", "BUY", "BUY"]


def test_pending_intents_skip_executed_and_out_of_session_ones(tmp_path: Path) -> None:
    db_path = tmp_path / "boustrategy.db"
    now = datetime(2026, 9, 10, 15, 32, tzinfo=UTC)
    intent = _live_intent(db_path, now - timedelta(hours=1))
    conn = connect(db_path)

    from app.broker.lifecycle import append_execution_event
    from app.schemas.broker_execution import BrokerExecutionEvent

    fresh = pending_live_intents(conn, _profile(), now=now)
    save_execution_packet(conn, live_execution_packet(intent))
    append_execution_event(
        conn,
        BrokerExecutionEvent(
            broker_event_id="ber_1_reviewed",
            broker_execution_record_id="ber_1",
            order_intent_id=intent.order_intent_id,
            execution_packet_id=f"ep_codex_{intent.order_intent_id}",
            execution_profile_id="codex",
            status="REVIEWED",
            occurred_at=datetime(2026, 8, 26, 14, 0, 10, tzinfo=UTC),
        ),
    )
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
    now = datetime(2026, 9, 10, 15, 32, tzinfo=UTC)
    intent = _live_intent(db_path, now - timedelta(hours=1))
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
    conn = connect(db_path)
    assert conn.execute("SELECT order_intent_id, model FROM execution_sessions").fetchall() == [
        (intent.order_intent_id, "gpt-5.6-sol")
    ]
    conn.close()


def test_execute_pending_reports_session_failure_and_clean_non_placement(tmp_path: Path) -> None:
    db_path = tmp_path / "boustrategy.db"
    now = datetime(2026, 9, 10, 15, 32, tzinfo=UTC)
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
            {
                "order_intent_id": intent.order_intent_id,
                "outcome": "blocked",
                "reason_code": "outside_regular_market_hours",
                "notes": "closed",
            },
            {},
        ),
        codex_home=tmp_path,
        log_dir=tmp_path / "b",
    )

    assert failed[0]["problems"] == ["session_failed"]
    assert failed[0]["session_failure"] == "session_timeout"
    assert clean[0]["problems"] == []
    assert clean[0]["report"]["reason_code"] == "outside_regular_market_hours"


def test_a_block_must_carry_a_known_label(tmp_path: Path) -> None:
    db_path = tmp_path / "boustrategy.db"
    now = datetime(2026, 9, 10, 15, 32, tzinfo=UTC)
    intent = _live_intent(db_path, now - timedelta(hours=1))
    unlabeled = {"order_intent_id": intent.order_intent_id, "outcome": "blocked", "notes": "?"}

    results = execute_pending(
        db_path,
        _profile(),
        now=now,
        session=_session_returning(unlabeled, {}),
        codex_home=tmp_path,
        log_dir=tmp_path / "logs",
    )

    assert results[0]["problems"] == ["unlabeled_block"]
    labeled = ExecutionReport.model_validate(
        {**unlabeled, "reason_code": "price_above_allowed_range"}
    )
    assert labeled.reason_code == "price_above_allowed_range"
    try:
        ExecutionReport.model_validate({**unlabeled, "reason_code": "felt risky"})
    except ValueError:
        pass
    else:
        raise AssertionError("an unknown block label was accepted")


def test_a_fill_triggers_a_snapshot_and_a_snapshot_failure_is_reported(tmp_path: Path) -> None:
    now = datetime(2026, 9, 10, 15, 32, tzinfo=UTC)
    taken: list[str] = []

    class Snapshot:
        portfolio_snapshot_id = "snap_after_fill"

    def snapshot() -> object:
        taken.append("taken")
        return Snapshot()

    def failing_snapshot() -> object:
        raise BrokerSessionFailure("session_timeout")

    def run(folder: str, outcome: str, after_fill: Any) -> list[dict[str, Any]]:
        db_path = tmp_path / folder / "boustrategy.db"
        db_path.parent.mkdir()
        intent = _live_intent(db_path, now - timedelta(hours=1))
        report = {"order_intent_id": intent.order_intent_id, "outcome": outcome}
        if outcome == "blocked":
            report["reason_code"] = "price_above_allowed_range"
        return execute_pending(
            db_path,
            _profile(),
            now=now,
            session=_session_returning(report, {}),
            codex_home=tmp_path,
            log_dir=db_path.parent / "logs",
            snapshot=after_fill,
        )

    # Holdings are published from snapshots, so a fill takes one straight away.
    assert run("filled", "filled", snapshot)[-1] == {"post_fill_snapshot": "snap_after_fill"}
    assert taken == ["taken"]
    # No fill, no snapshot.
    assert "post_fill_snapshot" not in run("blocked", "blocked", snapshot)[-1]
    assert taken == ["taken"]
    # A snapshot that fails is reported by name and doesn't abort the run.
    assert run("unlucky", "filled", failing_snapshot)[-1] == {
        "post_fill_snapshot": "failed",
        "reason": "BrokerSessionFailure",
    }


def test_verify_report_flags_intent_mismatch_and_unexpected_record(tmp_path: Path) -> None:
    db_path = tmp_path / "boustrategy.db"
    now = datetime(2026, 9, 10, 15, 32, tzinfo=UTC)
    intent = _live_intent(db_path, now)
    conn = connect(db_path)

    mismatch = verify_report(
        conn, intent, ExecutionReport(order_intent_id="other", outcome="not_placed")
    )

    assert mismatch == ["report_intent_mismatch"]
    assert "maximum order notional $20.00" in execution_prompt(intent, _profile())
    conn.close()


def test_an_intent_executes_only_in_the_session_it_was_decided(tmp_path: Path) -> None:
    db_path = tmp_path / "boustrategy.db"
    # Wednesday 18:15 ET, after the close: not executable Thursday, the price has moved on.
    overnight = _live_intent(db_path, datetime(2026, 9, 9, 22, 15, tzinfo=UTC))
    # Thursday 10:05 ET, in session: executable for the rest of Thursday's session only.
    in_session = _live_intent(tmp_path / "second.db", datetime(2026, 9, 10, 14, 5, tzinfo=UTC))
    thursday = datetime(2026, 9, 10, 14, 40, tzinfo=UTC)
    conn, second = connect(db_path), connect(tmp_path / "second.db")

    assert pending_live_intents(conn, _profile(), now=thursday) == []
    assert overnight.order_intent_id
    assert [
        item.order_intent_id for item in pending_live_intents(second, _profile(), now=thursday)
    ] == [in_session.order_intent_id]
    friday = datetime(2026, 9, 11, 13, 40, tzinfo=UTC)
    saturday = datetime(2026, 9, 12, 15, 0, tzinfo=UTC)
    assert pending_live_intents(second, _profile(), now=friday) == []
    assert pending_live_intents(second, _profile(), now=saturday) == []
    conn.close()
    second.close()


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
