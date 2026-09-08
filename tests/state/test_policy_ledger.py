import json
from datetime import UTC, datetime

import pytest

from app.policy.decision_policy import PortfolioContext
from app.schemas.decision_record import InvestmentDecisionRecord
from app.schemas.policy_reporting import PolicyEvaluationRecord, PolicyInputIdentity
from app.state.pipeline import process_decision
from app.storage.database import connect
from app.storage.records import get_order_intent, save_decision_record
from tests.fixtures.decision_records import valid_decision_record_data

NOW = datetime(2026, 6, 10, 15, tzinfo=UTC)


def test_ledger_exact_inputs_versions_and_injected_clock() -> None:
    conn = connect(":memory:")
    context = PortfolioContext(
        holdings_count=2,
        buy_add_trades_today=0,
        sell_trim_trades_today=0,
        primary_theme_weights={"other": 0.12},
    )
    result = process_decision(conn, valid_decision_record_data(), context, received_at=NOW)
    record = PolicyEvaluationRecord.model_validate_json(
        conn.execute("SELECT evaluation_json FROM policy_evaluations").fetchone()[0]
    )
    assert record.portfolio == context and record.authored_schema_version is None
    assert record.validator_version and len(record.validator_schema_sha256) == 64
    assert record.evaluated_at == NOW
    assert len(record.checks) == 14
    assert all(check.name for check in record.checks)
    assert {row[0] for row in conn.execute("SELECT occurred_at FROM status_events")} == {
        NOW.isoformat()
    }
    intent = get_order_intent(conn, result.order_intent_id or "")
    assert intent is not None and intent.created_at == NOW
    conn.close()


def test_ledger_and_decision_rollback_together_and_caller_controls_commit() -> None:
    conn = connect(":memory:")
    with pytest.raises(ValueError, match="missing"):
        process_decision(
            conn,
            valid_decision_record_data(),
            received_at=NOW,
            input_identity=PolicyInputIdentity(regime_snapshot_id="1900-01-01"),
        )
    for table in ("decision_records", "status_events", "policy_evaluations", "order_intents"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    process_decision(conn, valid_decision_record_data(), received_at=NOW, commit=False)
    assert conn.in_transaction
    conn.rollback()
    assert conn.execute("SELECT COUNT(*) FROM policy_evaluations").fetchone()[0] == 0
    conn.close()


def test_legacy_record_save_compares_semantic_defaults() -> None:
    conn = connect(":memory:")
    record = InvestmentDecisionRecord.model_validate(valid_decision_record_data())
    save_decision_record(conn, record)
    raw = record.model_dump(mode="json")
    raw.pop("schema_version")
    raw.pop("public_narrative")
    conn.execute("UPDATE decision_records SET record_json=?", (json.dumps(raw),))
    save_decision_record(conn, record)
    conn.close()


def test_live_lowercase_ticker_binds_actual_context() -> None:
    from app.reason.run import submit_decision
    from app.schemas.live_execution import LivePosition
    from app.schemas.order_intent import ExecutionMode
    from app.storage.records import save_live_portfolio_snapshot, save_reasoning_run
    from tests.storage.test_live_reasoning_records import _profile, _run, _snapshot

    conn = connect(":memory:")
    run, profile = _run(), _profile()
    snapshot = _snapshot().model_copy(
        update={
            "positions": [
                LivePosition(
                    ticker="NVDA", market_value=10, primary_theme_id="ai_compute_infrastructure"
                )
            ]
        }
    )
    save_live_portfolio_snapshot(conn, snapshot, profile)
    save_reasoning_run(conn, run)
    conn.execute(
        "INSERT INTO regime_snapshots VALUES (?, ?, ?, ?, ?, ?)",
        ("2026-08-27", "GREEN", "GREEN", 5, "{}", "2026-08-27T20:00:00+00:00"),
    )
    conn.commit()
    data = valid_decision_record_data()
    data.update(
        decision_id=run.reasoning_run_id + "_test", ticker=" nvda ", created_at=run.started_at
    )
    outcome = submit_decision(
        conn,
        data,
        run.session_date,
        execution_mode=ExecutionMode.LIVE,
        execution_profile_id=profile.execution_profile_id,
        execution_profile=profile,
        reasoning_run_id=run.reasoning_run_id,
        submission_snapshot_id=snapshot.portfolio_snapshot_id,
        submitted_at=run.started_at,
    )
    assert outcome.order_intent_id
    ledger = PolicyEvaluationRecord.model_validate_json(
        conn.execute("SELECT evaluation_json FROM policy_evaluations").fetchone()[0]
    )
    assert ledger.true_regime_state == "GREEN" and ledger.regime_snapshot is not None
    assert ledger.input_identity.current_weight == 0.1
    assert ledger.portfolio is not None and ledger.portfolio.primary_theme_weights == {}
    assert ledger.portfolio_snapshot == snapshot.model_dump(mode="json")
    conn.close()
