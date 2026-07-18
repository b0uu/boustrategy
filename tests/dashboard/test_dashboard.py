import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.dashboard.queries import overview, x_data
from app.dashboard.server import create_app, render_x_snippet
from app.storage.database import connect

ROUTES = ("/", "/portfolio", "/decisions", "/digests", "/x", "/regime", "/triggers")


def test_queries_degrade_on_empty_and_partial_databases(tmp_path: Path) -> None:
    empty = sqlite3.connect(":memory:")
    partial = sqlite3.connect(":memory:")
    partial.execute("CREATE TABLE x_accounts (handle TEXT)")

    empty_payload = overview(empty, tmp_path / "missing")
    partial_payload = x_data(partial)

    assert empty_payload["last_digest"] is None
    assert "paper" not in empty_payload
    assert partial_payload["accounts"] is None
    assert partial_payload["runs"] is None


def test_every_page_returns_200_for_empty_migrated_database(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.db"
    client = TestClient(create_app(db_path))

    for route in ROUTES:
        response = client.get(route)
        assert response.status_code == 200
        assert "none yet" in response.text or route == "/"


def test_every_page_returns_200_for_populated_database_and_escapes_content(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "populated.db"
    conn = connect(db_path)
    conn.execute(
        """
        INSERT INTO decision_records (decision_id, created_at, ticker, decision, record_json)
        VALUES ('d1', '2026-01-01', '<script>', 'BUY', ?)
        """,
        (json.dumps({"regime_state": "GREEN", "internal_notes": "<script>"}),),
    )
    conn.execute(
        """
        INSERT INTO status_events (subject_type, subject_id, status, occurred_at, detail)
        VALUES ('decision', 'd1', 'policy_rejected', '2026-01-01', '<b>unsafe</b>')
        """
    )
    conn.execute(
        """
        INSERT INTO trigger_events
            (trigger_id, trigger_type, subject, fired_at, details_json)
        VALUES ('t1', 'price_move', '<img>', '2026-01-01', '{"x":"<tag>"}')
        """
    )
    conn.commit()
    client = TestClient(create_app(db_path))

    for route in ROUTES:
        assert client.get(route).status_code == 200
    decisions = client.get("/decisions").text
    triggers = client.get("/triggers").text
    assert "<script>" not in decisions
    assert "&lt;script&gt;" in decisions
    assert "<img>" not in triggers


def test_dashboard_registers_no_mutation_routes(tmp_path: Path) -> None:
    app = create_app(tmp_path / "synthetic.db")

    for route in app.routes:
        methods: set[str] = getattr(route, "methods", set())
        assert methods <= {"GET", "HEAD"}


def test_x_snippet_public_switch_is_single_seam() -> None:
    text = "x" * 300

    assert len(render_x_snippet(text)) == 280
    assert render_x_snippet(text, public=True) == "[private snippet hidden]"


def test_overview_tiles_link_to_detail_pages(tmp_path: Path) -> None:
    response = TestClient(create_app(tmp_path / "synthetic.db")).get("/")

    assert "href='/portfolio'" in response.text
    assert "href='/regime'" in response.text
