import json
import sqlite3
from pathlib import Path
from time import perf_counter

import pytest
from fastapi.testclient import TestClient

from app.public.database import open_readonly
from app.public.publication import initialize, publish, revoke
from app.public.queries import feed
from app.public.server import create_public_app
from app.schemas.decision_record import InvestmentDecisionRecord
from app.state.pipeline import process_decision
from app.storage.database import connect
from tests.fixtures.decision_records import valid_decision_record_data


def seed(source: Path, count: int = 3) -> None:
    conn = connect(source)
    try:
        for index in range(count):
            data = valid_decision_record_data()
            data.update(
                decision_id=f"private_{index}",
                public_summary=f"Company outlook {index}",
                initial_thesis="PRIVATE_THESIS",
                internal_notes="PRIVATE_NOTE",
            )
            record = InvestmentDecisionRecord.model_validate(data)
            process_decision(conn, record.model_dump(), received_at=record.created_at)
    finally:
        conn.close()


def test_readonly_missing_database_never_creates_file_and_rejects_writes(tmp_path: Path) -> None:
    source = tmp_path / "missing" / "source.db"
    with open_readonly(source) as conn:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("CREATE TABLE secret(value)")
    client = TestClient(create_public_app(source, tmp_path / "no-ui"))
    assert client.get("/api/public/v2/decisions").json()["items"] == []
    assert client.get("/api/public/v2/portfolios/paper/overview").status_code == 200
    assert not source.parent.exists()


def test_v2_detail_never_serializes_private_source_state(tmp_path: Path) -> None:
    source, public = tmp_path / "source.db", tmp_path / "published.db"
    conn = connect(source)
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
    conn.close()
    publish(source, public)
    client = TestClient(create_public_app(public))
    item = client.get("/api/public/v2/decisions?portfolio_id=paper").json()["items"][0]
    responses = (
        client.get(f"/api/public/v2/decisions/{item['public_id']}"),
        client.get(f"/api/public/v2/decisions/{item['public_id']}/export"),
    )
    sensitive = (
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
    )
    published_bytes = public.read_bytes()
    for response in responses:
        assert response.status_code == 200
        for private_value in sensitive:
            assert private_value not in response.text
    for private_value in sensitive:
        assert private_value.encode() not in published_bytes


def test_tied_timestamps_cursor_stability_search_and_live_paper_scope(tmp_path: Path) -> None:
    source, public = tmp_path / "source.db", tmp_path / "published.db"
    seed(source)
    assert publish(source, public)["inserted"] == 3
    client = TestClient(create_public_app(public))
    first = client.get(
        "/api/public/v2/decisions", params={"portfolio_id": "paper", "limit": 1}
    ).json()
    assert first["total"] == 3
    assert len(first["items"]) == 1
    assert client.get("/api/public/v2/decisions").json()["items"] == []
    assert client.get("/api/public/v2/portfolios/live/overview").json()["equity"] is None
    old_ids = {first["items"][0]["public_id"]}
    seed(source, count=4)
    publish(source, public)
    cursor = first["next_cursor"]
    while cursor:
        page = client.get(
            "/api/public/v2/decisions",
            params={"portfolio_id": "paper", "limit": 1, "cursor": cursor},
        ).json()
        assert page["total"] == 3
        for item in page["items"]:
            assert item["public_id"] not in old_ids
            old_ids.add(item["public_id"])
        cursor = page["next_cursor"]
    assert len(old_ids) == 3
    search = client.get(
        "/api/public/v2/decisions", params={"portfolio_id": "paper", "q": "outlook 3"}
    ).json()
    assert search["total"] == 1
    assert search["items"][0]["public_summary"] == "Company outlook 3"
    detail = client.get(f"/api/public/v2/decisions/{search['items'][0]['public_id']}")
    for secret in ("PRIVATE_THESIS", "PRIVATE_NOTE", "private_3", "src_001", "sp_001"):
        assert secret not in detail.text
    assert publish(source, public) == {"inserted": 0, "updated": 0, "withdrawn": 0}


def test_changed_status_requires_restart_and_revocation_survives_publish(tmp_path: Path) -> None:
    source, public = tmp_path / "source.db", tmp_path / "published.db"
    seed(source)
    publish(source, public)
    client = TestClient(create_public_app(public))
    params = {"portfolio_id": "paper", "limit": 1, "policy": "approved"}
    first = client.get("/api/public/v2/decisions", params=params).json()
    conn = connect(source)
    conn.execute(
        "INSERT INTO status_events(subject_type, subject_id, status, occurred_at) "
        "VALUES('decision', 'private_0', 'policy_rejected', '2026-06-11')"
    )
    conn.commit()
    conn.close()
    publish(source, public)
    response = client.get(
        "/api/public/v2/decisions", params={**params, "cursor": first["next_cursor"]}
    )
    assert response.status_code == 409
    public_id = first["items"][0]["public_id"]
    assert revoke(public, public_id)
    publish(source, public)
    assert client.get(f"/api/public/v2/decisions/{public_id}").status_code == 410
    assert (
        public_id
        not in client.get("/api/public/v2/decisions", params={"portfolio_id": "paper"}).text
    )


def test_withdrawal_hides_legacy_links_and_position_summary(tmp_path: Path) -> None:
    source, public = tmp_path / "source.db", tmp_path / "published.db"
    seed(source, count=1)
    conn = connect(source)
    conn.execute("INSERT INTO paper_positions VALUES ('NVDA', 1, 100, '2026-06-10', 'ai')")
    conn.commit()
    conn.close()
    publish(source, public)
    client = TestClient(create_public_app(public))
    old_link = "/api/public/v2/legacy-decisions/NVDA/2026-06-10T12:00:00+00:00"
    assert client.get(old_link).status_code == 200
    item = client.get("/api/public/v2/decisions", params={"portfolio_id": "paper"}).json()["items"][
        0
    ]
    assert revoke(public, item["public_id"])
    assert client.get(old_link).status_code == 410
    positions = client.get("/api/public/v2/portfolios/paper/positions").json()["items"]
    assert len(positions) == 1
    assert positions[0]["market_value"] is None
    assert positions[0]["latest_public_summary"] is None
    assert client.get("/api/public/v2/decisions?portfolio_id=paper").json()["items"] == []


def test_unpublication_is_atomic_and_invalid_source_does_not_hide_records(tmp_path: Path) -> None:
    source, public = tmp_path / "source.db", tmp_path / "published.db"
    seed(source, count=1)
    publish(source, public)
    with pytest.raises(FileNotFoundError):
        publish(tmp_path / "absent.db", public)
    conn = connect(source)
    conn.execute(
        "UPDATE decision_records SET record_json=json_set(record_json, '$.public_summary', '')"
    )
    conn.commit()
    conn.close()
    assert publish(source, public)["withdrawn"] == 1
    with open_readonly(public) as conn:
        assert feed(conn, portfolio_id="paper")["total"] == 0


def test_spa_never_handles_api_typos_or_missing_assets(tmp_path: Path) -> None:
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("<html>app</html>")
    client = TestClient(create_public_app(tmp_path / "absent.db", ui))
    assert client.get("/").status_code == 200
    for route in ("/api/public/v2/typo", "/api/private", "/assets/missing.js", "/operate"):
        assert client.get(route).status_code == 404
    assert client.get("/api/public/v2/decisions?limit=101").status_code == 422
    assert client.get("/api/public/v2/decisions?cursor=garbage").status_code == 422
    assert client.get("/api/public/v2/decisions?since=2026-01-01").status_code == 422


def test_large_feed_uses_fixed_query_count_and_indexed_search(tmp_path: Path) -> None:
    path = tmp_path / "public.db"
    conn = initialize(path)
    conn.executemany(
        "INSERT INTO public_decisions(source_key, public_id, portfolio_id, created_at, ticker, "
        "action, policy, lifecycle, summary, content) VALUES (?, ?, 'live', ?, 'NVDA', 'BUY', "
        "'approved', 'policy_approved', ?, ?)",
        (
            (
                str(i),
                f"dec_{i:06}",
                "2026-06-10T12:00:00+00:00",
                f"Searchable company {i}",
                json.dumps({"public_id": f"dec_{i:06}"}),
            )
            for i in range(100_000)
        ),
    )
    conn.commit()
    conn.close()
    statements: list[str] = []
    with open_readonly(path) as read:
        read.set_trace_callback(statements.append)
        started = perf_counter()
        result = feed(read, portfolio_id="live")
        elapsed = perf_counter() - started
        assert len(result["items"]) == 25
        assert result["total"] == 100_000
        query_count = len(statements)
        statements.clear()
        assert len(feed(read, portfolio_id="live", limit=100)["items"]) == 100
        assert len(statements) == query_count
        assert feed(read, portfolio_id="live", q="99999")["total"] == 1
        plan = read.execute(
            "EXPLAIN QUERY PLAN SELECT public_id FROM public_decisions WHERE portfolio_id='live' "
            "AND revoked=0 AND withdrawn=0 ORDER BY created_at DESC, public_id DESC LIMIT 25"
        ).fetchall()
        assert any("public_feed" in row[3] for row in plan)
    assert elapsed < 1.0


def test_live_snapshot_scope_and_all_cash_do_not_invent_quantity_or_cash(tmp_path: Path) -> None:
    source, public = tmp_path / "source.db", tmp_path / "published.db"
    seed(source, count=2)
    conn = connect(source)
    conn.execute(
        "UPDATE order_intents SET execution_mode='LIVE', execution_profile_id='private_profile' "
        "WHERE decision_id='private_0'"
    )
    conn.execute("DELETE FROM policy_evaluations WHERE decision_id='private_0'")
    snapshot = {
        "portfolio_snapshot_id": "private_snapshot",
        "execution_profile_id": "private_profile",
        "broker_account_fingerprint": "0123456789abcdef",
        "captured_at": "2026-06-10T12:00:00+00:00",
        "account_equity": 5000,
        "buying_power": 10000,
        "positions": [],
    }
    conn.execute(
        "INSERT INTO live_portfolio_snapshots VALUES (?, ?, ?, ?, ?)",
        (
            snapshot["portfolio_snapshot_id"],
            snapshot["execution_profile_id"],
            snapshot["captured_at"],
            snapshot["account_equity"],
            json.dumps(snapshot),
        ),
    )
    conn.commit()
    conn.close()
    publish(source, public, live_profiles=("private_profile",))
    client = TestClient(create_public_app(public))
    assert client.get("/api/public/v2/decisions").json()["total"] == 1
    assert client.get("/api/public/v2/decisions?portfolio_id=paper").json()["total"] == 1
    overview = client.get("/api/public/v2/portfolios/live/overview")
    assert overview.json()["equity"] == 5000
    assert overview.json()["cash"] is None
    assert overview.json()["return_percent"] is None
    assert "private_profile" not in overview.text
    positions = client.get("/api/public/v2/portfolios/live/positions").json()
    assert positions["status"] == "available"
    assert positions["items"] == []


def test_v2_preserves_partial_and_unfunded_reporting_states(tmp_path: Path) -> None:
    from app.performance.storage import ingest
    from app.schemas.reporting import ValuationObservation
    from tests.performance.test_reporting import ACCOUNT, common, valuation

    source, public = tmp_path / "source.db", tmp_path / "published.db"
    conn = connect(source)
    partial = ValuationObservation.model_validate(
        {
            **common("partial", 10),
            "equity": "100",
            "cash": "0",
            "positions": [{"ticker": "NVDA"}],
            "complete": False,
        }
    )
    ingest(conn, partial)
    conn.commit()
    conn.close()
    publish(source, public, live_account_id=ACCOUNT)
    client = TestClient(create_public_app(public))

    overview = client.get("/api/public/v2/portfolios/live/overview").json()
    assert overview["status"] == "partial"
    assert overview["portfolio_state"] == "partial"
    assert overview["equity"] == "100"
    assert overview["cash"] == "0"
    positions = client.get("/api/public/v2/portfolios/live/positions").json()
    assert positions["status"] == "available"
    assert positions["valuation_status"] == "partial"
    assert positions["items"][0]["ticker"] == "NVDA"
    assert positions["items"][0]["market_value"] is None
    performance = client.get(
        "/api/public/v2/portfolios/live/performance", params={"range": "All"}
    ).json()
    assert performance["status"] == "unavailable"
    assert performance["return_percent"] is None

    conn = connect(source)
    ingest(conn, valuation("zero", 11, "0"))
    conn.commit()
    conn.close()
    publish(source, public, live_account_id=ACCOUNT)
    overview = client.get("/api/public/v2/portfolios/live/overview").json()
    assert overview["portfolio_state"] == "zero_balance"
    assert overview["equity"] == "0"
    assert overview["cash"] == "0"
    assert client.get("/api/public/v2/portfolios/live/positions").json()["items"] == []


def test_v2_runtime_distinguishes_unpublished_from_recorded_manual_state(tmp_path: Path) -> None:
    missing = tmp_path / "missing.db"
    client = TestClient(create_public_app(missing))
    response = client.get("/api/public/v2/portfolios/live/runtime")
    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"
    assert response.json()["reason"] == "runtime_not_published"
    assert response.json()["latest_run"] is None
    assert response.json()["schedules"] == []
    assert not missing.exists()

    source, public = tmp_path / "source.db", tmp_path / "published.db"
    conn = connect(source)
    conn.close()
    publish(source, public)
    response = TestClient(create_public_app(public)).get("/api/public/v2/portfolios/live/runtime")
    assert response.status_code == 200
    assert response.json()["schedule_mode"] == "manual"
    assert response.json()["schedules"] == []
    assert "status" not in response.json()


def test_v2_legacy_resolution_is_exact_and_respects_retraction(tmp_path: Path) -> None:
    from urllib.parse import quote

    source, public = tmp_path / "source.db", tmp_path / "published.db"
    seed(source, count=1)
    publish(source, public)
    client = TestClient(create_public_app(public))
    item = client.get("/api/public/v2/decisions?portfolio_id=paper").json()["items"][0]
    legacy_url = (
        f"/api/public/v2/legacy-decisions/{item['ticker']}/{quote(item['created_at'], safe='')}"
    )
    response = client.get(legacy_url)
    assert response.status_code == 200
    assert response.json()["public_id"] == item["public_id"]

    assert revoke(public, item["public_id"])
    assert client.get(legacy_url).status_code == 410
    assert client.get("/api/public/v2/legacy-decisions/NVDA/not-a-time").status_code == 404

    ambiguous_source, ambiguous_public = tmp_path / "ambiguous.db", tmp_path / "ambiguous-public.db"
    seed(ambiguous_source, count=2)
    publish(ambiguous_source, ambiguous_public)
    ambiguous = TestClient(create_public_app(ambiguous_public))
    assert (
        ambiguous.get(
            "/api/public/v2/legacy-decisions/NVDA/2026-06-10T12%3A00%3A00%2B00%3A00"
        ).status_code
        == 404
    )


def test_get_preserves_database_bytes_and_closes_connection(tmp_path: Path) -> None:
    source, public = tmp_path / "source.db", tmp_path / "published.db"
    seed(source, count=1)
    publish(source, public)
    before = (source.read_bytes(), public.read_bytes())
    client = TestClient(create_public_app(public))
    assert client.get("/api/public/v2/decisions").status_code == 200
    assert client.get("/api/public/v2/portfolios/paper/overview").status_code == 200
    assert before == (source.read_bytes(), public.read_bytes())
    with open_readonly(public) as conn:
        assert conn.execute("PRAGMA query_only").fetchone()[0] == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        conn.execute("SELECT 1")


def test_search_theme_and_exact_ticker_priority_continue_consistently(tmp_path: Path) -> None:
    source, public = tmp_path / "source.db", tmp_path / "published.db"
    seed(source, count=2)
    conn = connect(source)
    conn.execute(
        "UPDATE decision_records SET ticker='AMD', record_json=json_set(record_json, "
        "'$.ticker', 'AMD', '$.public_summary', 'NVDA competitor') "
        "WHERE decision_id='private_1'"
    )
    conn.commit()
    conn.close()
    publish(source, public)
    client = TestClient(create_public_app(public))
    first = client.get(
        "/api/public/v2/decisions", params={"portfolio_id": "paper", "q": "NVDA", "limit": 1}
    ).json()
    assert first["items"][0]["ticker"] == "NVDA"
    next_page = client.get(
        "/api/public/v2/decisions",
        params={"portfolio_id": "paper", "q": "NVDA", "limit": 1, "cursor": first["next_cursor"]},
    ).json()
    assert next_page["items"][0]["ticker"] == "AMD"
    assert (
        client.get(
            "/api/public/v2/decisions", params={"portfolio_id": "paper", "q": "semiconductors"}
        ).json()["total"]
        == 2
    )
    assert (
        client.get(
            "/api/public/v2/decisions",
            params={"portfolio_id": "paper", "q": "different", "cursor": first["next_cursor"]},
        ).status_code
        == 422
    )


def test_ambiguous_legacy_timestamp_does_not_pick_a_record(tmp_path: Path) -> None:
    source, public = tmp_path / "source.db", tmp_path / "published.db"
    seed(source, count=2)
    publish(source, public)
    client = TestClient(create_public_app(public))
    assert (
        client.get("/api/public/v2/legacy-decisions/NVDA/2026-06-10T12:00:00+00:00").status_code
        == 404
    )


def test_published_legacy_views_never_rerender_changed_private_source(tmp_path: Path) -> None:
    source, public = tmp_path / "source.db", tmp_path / "published.db"
    seed(source, count=2)
    publish(source, public)
    client = TestClient(create_public_app(public))
    items = client.get("/api/public/v2/decisions?portfolio_id=paper").json()["items"]
    assert revoke(public, items[0]["public_id"])
    conn = connect(source)
    conn.execute(
        "UPDATE decision_records SET record_json=json_set(record_json, "
        "'$.public_summary', 'UNPUBLISHED_EDIT')"
    )
    conn.commit()
    conn.close()
    feed_response = client.get("/api/public/v2/decisions?portfolio_id=paper")
    assert feed_response.status_code == 200
    assert len(feed_response.json()["items"]) == 1
    assert feed_response.json()["items"][0]["public_summary"] == items[1]["public_summary"]
    assert "UNPUBLISHED_EDIT" not in feed_response.text
    assert "PRIVATE_THESIS" not in feed_response.text


def test_published_x_usage_keeps_recorded_flags_and_hides_private_summary(tmp_path: Path) -> None:
    source, public = tmp_path / "source.db", tmp_path / "published.db"
    seed(source, count=1)
    conn = connect(source)
    conn.execute(
        "UPDATE decision_records SET record_json=json_set(record_json, "
        "'$.x_signal_usage', json(?))",
        (
            json.dumps(
                {
                    "used": True,
                    "usage_type": "COUNTER_THESIS",
                    "summary": "PRIVATE_X",
                    "confirmed_outside_x": False,
                }
            ),
        ),
    )
    conn.commit()
    conn.close()
    publish(source, public)
    client = TestClient(create_public_app(public))
    response = client.get("/api/public/v2/legacy-decisions/NVDA/2026-06-10T12:00:00+00:00")
    assert response.json()["x_usage"] == {
        "used": True,
        "usage_type": "COUNTER_THESIS",
        "summary": "",
        "confirmed_outside_x": False,
    }
    assert "PRIVATE_X" not in response.text


def test_company_metadata_is_searchable_and_unknown_paper_cost_remains_nullable(
    tmp_path: Path,
) -> None:
    from app.performance.storage import ingest
    from app.schemas.reporting import ValuationObservation

    source, public = tmp_path / "source.db", tmp_path / "published.db"
    seed(source, count=1)
    conn = connect(source)
    report = ValuationObservation.model_validate(
        {
            "observation_id": "paper-report",
            "external_event_id": "paper-report",
            "mode": "paper",
            "account_id": "paper",
            "occurred_at": "2026-06-10T20:00:00Z",
            "recorded_at": "2026-06-10T20:00:00Z",
            "equity": "100",
            "cash": "0",
            "complete": False,
            "positions": [{"ticker": "NVDA", "name": "NVIDIA Corporation", "market_value": "100"}],
        }
    )
    ingest(conn, report)
    conn.commit()
    conn.close()
    publish(source, public)
    client = TestClient(create_public_app(public))
    response = client.get("/api/public/v2/decisions?portfolio_id=paper&q=NVIDIA")
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["company_name"] == "NVIDIA Corporation"
    positions = client.get("/api/public/v2/portfolios/paper/positions")
    assert positions.status_code == 200
    assert positions.json()["items"][0]["average_cost"] is None
    assert positions.json()["items"][0]["shares"] is None
