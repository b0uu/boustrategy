import json
from datetime import date, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.dashboard.queries import decision_detail
from app.dashboard.server import create_app
from app.schemas.decision_record import InvestmentDecisionRecord
from app.schemas.order_intent import ExecutionMode
from app.schemas.reasoning_run import ReasoningRun
from app.state.pipeline import process_decision
from app.storage.database import connect
from app.storage.records import save_reasoning_run
from tests.fixtures.decision_records import valid_decision_record_data


def _record(**overrides: object) -> InvestmentDecisionRecord:
    data = valid_decision_record_data()
    data.update(overrides)
    return InvestmentDecisionRecord.model_validate(data)


def test_decision_feed_links_to_full_real_data_trace_and_escapes_content(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "trace.db"
    conn = connect(db_path)
    record = _record(
        initial_thesis="Initial <script>alert('initial')</script>",
        counter_thesis="Demand expectations may already be priced in.",
        adversarial_refinement="Size for valuation and demand risk.",
        refined_thesis="Refined thesis supported by persisted sources.",
        what_is_priced_in="Strong accelerator demand.",
        x_signal_usage={
            "used": True,
            "usage_type": "COUNTER_THESIS",
            "summary": "X highlighted crowding, not the core thesis.",
            "confirmed_outside_x": False,
        },
        public_summary="Public <img src=x onerror=alert(1)> summary.",
    )
    process_decision(conn, record.model_dump(), received_at=record.created_at)
    conn.execute(
        """
        INSERT INTO trigger_events
            (trigger_id, trigger_type, subject, fired_at, details_json, status)
        VALUES (?, 'price_move', 'NVDA', ?, ?, 'consumed')
        """,
        (
            record.trigger_id,
            record.created_at.isoformat(),
            json.dumps({"move": "<b>five percent</b>"}),
        ),
    )
    conn.execute(
        """
        INSERT INTO regime_snapshots
            (snapshot_date, regime, raw_regime, score, components_json, computed_at)
        VALUES (?, 'GREEN', 'GREEN', 4, ?, ?)
        """,
        (
            record.created_at.date().isoformat(),
            json.dumps({"trend": 1, "breadth": 1}),
            record.created_at.isoformat(),
        ),
    )
    conn.commit()
    client = TestClient(create_app(db_path))

    feed = client.get("/decisions")
    trace = client.get(f"/decisions/{record.decision_id}")

    assert feed.status_code == 200
    assert f"href='/decisions/{record.decision_id}'" in feed.text
    assert trace.status_code == 200
    assert "Recorded thesis chain" in trace.text
    assert "Refined thesis supported by persisted sources." in trace.text
    assert "Company demand is linked to AI infrastructure spending." in trace.text
    assert "AI capex guidance weakens materially." in trace.text
    assert "SB-002" in trace.text
    assert "ai_semiconductors" in trace.text
    assert "sp_001" in trace.text
    assert "Portfolio management conditions" in trace.text
    assert "X highlighted crowding" in trace.text
    assert "schema validated" in trace.text
    assert "policy approved" in trace.text
    assert "oi_dec_001" in trace.text
    assert "&lt;script&gt;" in trace.text
    assert "<script>alert('initial')</script>" not in trace.text
    assert "<img src=x" not in trace.text
    assert "&lt;b&gt;five percent&lt;/b&gt;" in trace.text


def test_decision_trace_returns_404_for_unknown_record(tmp_path: Path) -> None:
    response = TestClient(create_app(tmp_path / "empty.db")).get("/decisions/missing")

    assert response.status_code == 404


def test_decision_trace_and_execution_ledger_never_render_raw_sensitive_json(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "live-trace.db"
    conn = connect(db_path)
    record = _record(decision_id="rr_2026-06-10_close_codex_dec_001")
    outcome = process_decision(
        conn,
        record.model_dump(),
        received_at=record.created_at,
        execution_mode=ExecutionMode.LIVE,
        execution_profile_id="codex",
    )
    assert outcome.order_intent_id is not None
    run = ReasoningRun(
        reasoning_run_id="rr_2026-06-10_close_codex",
        session_date=date(2026, 6, 10),
        slot="close",
        execution_profile_id="codex",
        model_label="Codex",
        shared_bundle_path="data/reason/2026-06-10/shared_bundle.md",
        shared_bundle_sha256="a" * 64,
        portfolio_snapshot_id="snap_codex",
        started_at=record.created_at - timedelta(minutes=2),
    )
    save_reasoning_run(conn, run)
    conn.execute(
        "INSERT INTO reasoning_run_decisions VALUES (?, ?, ?)",
        (run.reasoning_run_id, record.decision_id, "snap_codex_submit"),
    )
    sensitive_values = {
        "fingerprint": "0123456789abcdef",
        "account": "ACCOUNT-778899",
        "raw": "RAW_BROKER_RESPONSE_SECRET",
    }
    conn.execute(
        """
        INSERT INTO live_portfolio_snapshots
            (portfolio_snapshot_id, execution_profile_id, captured_at, account_equity,
             snapshot_json)
        VALUES ('snap_codex_submit', 'codex', ?, 5000, ?)
        """,
        (record.created_at.isoformat(), json.dumps(sensitive_values)),
    )
    created_at = record.created_at + timedelta(minutes=1)
    expires_at = created_at + timedelta(minutes=1)
    conn.execute(
        """
        INSERT INTO live_execution_packets
            (execution_packet_id, order_intent_id, execution_profile_id, created_at,
             expires_at, ticker, side, notional, limit_price, packet_json)
        VALUES ('ep_safe', ?, 'codex', ?, ?, 'NVDA', 'BUY', 20, 100, ?)
        """,
        (
            outcome.order_intent_id,
            created_at.isoformat(),
            expires_at.isoformat(),
            json.dumps(sensitive_values),
        ),
    )
    conn.execute(
        """
        INSERT INTO broker_execution_records
            (broker_execution_record_id, order_intent_id, execution_packet_id,
             execution_profile_id, account_alias, submitted_at, ticker, side, status,
             broker_order_id, record_json)
        VALUES ('ber_safe', ?, 'ep_safe', 'codex', 'codex-agentic', ?, 'NVDA', 'BUY',
                'SUBMITTED', 'broker-order-safe', ?)
        """,
        (outcome.order_intent_id, created_at.isoformat(), json.dumps(sensitive_values)),
    )
    conn.execute(
        """
        INSERT INTO broker_execution_events
            (broker_event_id, broker_execution_record_id, order_intent_id,
             execution_packet_id, execution_profile_id, status, occurred_at, detail,
             event_json)
        VALUES ('event_safe', 'ber_safe', ?, 'ep_safe', 'codex', 'SUBMITTED', ?,
                'RAW_EVENT_DETAIL_SECRET', ?)
        """,
        (outcome.order_intent_id, created_at.isoformat(), json.dumps(sensitive_values)),
    )
    conn.commit()
    client = TestClient(create_app(db_path, live_config_path=tmp_path / "missing.json"))

    payload = decision_detail(conn, record.decision_id)
    trace = client.get(f"/decisions/{record.decision_id}")
    ledger = client.get("/executions")

    assert payload is not None
    assert "snapshot_json" not in repr(payload)
    assert "record_json" not in repr(payload)
    assert "event_json" not in repr(payload)
    assert "packet_json" not in repr(payload)
    assert "ep_safe" in trace.text
    for sensitive in [*sensitive_values.values(), "RAW_EVENT_DETAIL_SECRET"]:
        assert sensitive not in trace.text
        assert sensitive not in ledger.text
