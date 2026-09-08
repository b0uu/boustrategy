import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.public.server import create_public_app
from app.schemas.decision_record import InvestmentDecisionRecord
from app.state.pipeline import process_decision
from app.storage.database import connect
from tests.fixtures.decision_records import valid_decision_record_data


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
    db_path = tmp_path / "public.db"
    return TestClient(create_public_app(db_path, tmp_path / "missing-ui")), db_path


def test_public_api_has_only_read_methods_and_empty_states(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)

    response = client.get("/api/public/v1/dashboard")

    assert response.status_code == 200
    assert response.json()["performance"]["status"] == "unavailable"
    assert response.json()["decisions"] == []
    assert client.head("/api/public/v1/dashboard").status_code == 200
    assert client.post("/api/public/v1/dashboard").status_code == 405
    assert client.put("/api/public/v1/dashboard").status_code == 405


def test_public_projection_filters_sources_ids_and_live_details(tmp_path: Path) -> None:
    client, db_path = _client(tmp_path)
    conn = connect(db_path)
    data = valid_decision_record_data()
    data["public_summary"] = "Public <script>alert(1)</script> summary"
    data["internal_notes"] = "PRIVATE_INTERNAL_NOTE"
    data["source_pack_id"] = "PRIVATE_PACKET_ID"
    data["source_claims"] = [
        {
            "claim": "Publishable company claim",
            "source_ids": ["PRIVATE_SOURCE_ID"],
            "source_type": "COMPANY_IR",
            "source_timestamp": data["created_at"],
            "confidence": 0.8,
            "public_safe": True,
        },
        {
            "claim": "PRIVATE_UNSAFE_CLAIM",
            "source_ids": ["PRIVATE_SOURCE_ID_2"],
            "source_type": "NEWS",
            "source_timestamp": data["created_at"],
            "confidence": 0.8,
            "public_safe": False,
        },
        {
            "claim": "PRIVATE_INTERNAL_MEMO",
            "source_ids": ["PRIVATE_SOURCE_ID_3"],
            "source_type": "INTERNAL_MEMO",
            "source_timestamp": data["created_at"],
            "confidence": 0.8,
            "public_safe": True,
        },
    ]
    data["x_signal_usage"] = {
        "used": True,
        "usage_type": "COUNTER_THESIS",
        "summary": "PRIVATE_X_DETAIL",
        "confirmed_outside_x": False,
    }
    record = InvestmentDecisionRecord.model_validate(data)
    outcome = process_decision(conn, record.model_dump(), received_at=record.created_at)
    conn.execute(
        "INSERT INTO trigger_events VALUES "
        "(?, 'price_move', 'PRIVATE_TRIGGER_SUBJECT', ?, ?, 'consumed')",
        (record.trigger_id, record.created_at.isoformat(), json.dumps({"raw": "PRIVATE_RAW"})),
    )
    conn.execute(
        "INSERT INTO regime_snapshots VALUES (?, 'GREEN', 'GREEN', 4, ?, ?)",
        (
            record.created_at.date().isoformat(),
            json.dumps({"trend": 0.75, "private_note": "PRIVATE_COMPONENT"}),
            record.created_at.isoformat(),
        ),
    )
    assert outcome.order_intent_id is not None
    conn.execute(
        "INSERT INTO broker_execution_events VALUES "
        "('PRIVATE_EVENT_ID', 'PRIVATE_RECORD_ID', ?, 'PRIVATE_PACKET_ID', 'PRIVATE_PROFILE', "
        "'FAILED', ?, 'PRIVATE_RAW_ERROR', ?)",
        (
            outcome.order_intent_id,
            record.created_at.isoformat(),
            json.dumps({"secret": "CREDENTIAL"}),
        ),
    )
    conn.commit()

    response = client.get(
        f"/api/public/v1/decisions/{record.ticker}/{record.created_at.isoformat()}"
    )
    payload = response.json()
    serialized = response.text

    assert response.status_code == 200
    assert payload["claims"] == [
        {
            "claim": "Publishable company claim",
            "source_type": "COMPANY_IR",
            "source_timestamp": record.created_at.isoformat(),
        }
    ]
    assert payload["trigger"]["subject"] == "NVDA"
    assert payload["outcome"]["lifecycle"] == "awaiting_paper_price"
    assert payload["x_usage"]["summary"] == ""
    for sensitive in (
        record.decision_id,
        "PRIVATE_INTERNAL_NOTE",
        "PRIVATE_PACKET_ID",
        "PRIVATE_SOURCE_ID",
        "PRIVATE_UNSAFE_CLAIM",
        "PRIVATE_INTERNAL_MEMO",
        "PRIVATE_X_DETAIL",
        "PRIVATE_TRIGGER_SUBJECT",
        "PRIVATE_RAW_ERROR",
        "PRIVATE_PROFILE",
        "CREDENTIAL",
        "confidence",
    ):
        assert sensitive not in serialized


def test_internal_routes_are_not_mounted_on_public_app(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)

    for route in ("/operate", "/operate/live", "/portfolio", "/executions", "/x"):
        assert client.get(route).status_code == 404
