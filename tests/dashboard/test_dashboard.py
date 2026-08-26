import json
import re
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.dashboard.queries import overview, x_data
from app.dashboard.server import create_app, render_x_snippet
from app.reason.run import PreparationResult
from app.schemas.decision_record import RegimeState
from app.storage.database import connect

ROUTES = (
    "/",
    "/operate",
    "/portfolio",
    "/decisions",
    "/digests",
    "/x",
    "/regime",
    "/triggers",
)


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
        assert "none yet" in response.text or route in {"/", "/operate"}


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
    assert "<td><script>" not in decisions
    assert "&lt;script&gt;" in decisions
    assert "<img>" not in triggers


def test_dashboard_registers_only_supervised_preparation_mutation(tmp_path: Path) -> None:
    app = create_app(tmp_path / "synthetic.db")

    post_routes = []
    for route in app.routes:
        methods: set[str] = getattr(route, "methods", set())
        if "POST" in methods:
            post_routes.append(getattr(route, "path", ""))
        else:
            assert methods <= {"GET", "HEAD"}

    assert post_routes == ["/operate/prepare"]


def test_operator_page_explains_manual_boundary_and_blocks_unready_prepare(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(tmp_path / "boustrategy.db"))

    response = client.get("/operate?date=2026-08-25&slot=close")

    assert response.status_code == 200
    assert "Copy digester prompt" in response.text
    assert "Nothing runs or spends X credits" in response.text
    assert "<button type='submit' disabled>Prepare paper session</button>" in response.text
    assert "data-copy='reasoning-prompt' disabled" in response.text


def test_operator_prepare_rejects_missing_request_token(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "boustrategy.db"))

    response = client.post("/operate/prepare", data={"date": "2026-08-25", "slot": "close"})

    assert response.status_code == 403


def test_operator_prepare_runs_and_unlocks_reasoning_prompt(tmp_path: Path) -> None:
    db_path = tmp_path / "boustrategy.db"
    conn = connect(db_path)
    conn.execute(
        """
        INSERT INTO x_runs (run_id, slot, started_at, finished_at, status)
        VALUES ('2026-08-25-close', 'close', '2026-08-25T20:00:00Z',
                '2026-08-25T20:05:00Z', 'digested')
        """
    )
    conn.commit()
    digest_dir = tmp_path / "digests"
    digest_dir.mkdir()
    (digest_dir / "2026-08-25.md").write_text("# Digest", encoding="utf-8")

    called: list[date] = []

    def fake_prepare(
        conn: sqlite3.Connection,
        on_date: date,
        out_dir: str | Path,
        *,
        digest_dir: str | Path = "data/digests",
        watchlist_path: str | Path = "docs/watchlist.md",
    ) -> PreparationResult:
        del conn, watchlist_path
        called.append(on_date)
        output = Path(out_dir)
        output.mkdir(parents=True)
        bundle_path = output / "bundle.md"
        bundle_path.write_text("# Intake", encoding="utf-8")
        result = PreparationResult(
            session_date=on_date,
            prepared_at=datetime(2026, 8, 25, 20, 6, tzinfo=UTC),
            digest_path=(Path(digest_dir) / f"{on_date.isoformat()}.md").as_posix(),
            completed_digest_runs=["2026-08-25-close"],
            refreshed_price_bars={},
            refreshed_calendar_events={},
            fills_created=0,
            intents_awaiting_price=0,
            trigger_counts={},
            regime=RegimeState.GREEN,
            raw_regime=RegimeState.GREEN,
            regime_score=4,
            bundle_path=bundle_path.as_posix(),
        )
        (output / "preparation.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
        return result

    client = TestClient(create_app(db_path, preparation_runner=fake_prepare))
    page = client.get("/operate?date=2026-08-25&slot=close")
    token_match = re.search(r"name='csrf_token' value='([^']+)'", page.text)
    assert token_match is not None

    response = client.post(
        "/operate/prepare",
        data={
            "csrf_token": token_match.group(1),
            "date": "2026-08-25",
            "slot": "close",
        },
    )

    assert response.status_code == 200
    assert called == [date(2026, 8, 25)]
    assert "Preparation completed." in response.text
    assert "data-copy='reasoning-prompt' disabled" not in response.text


def test_x_snippet_public_switch_is_single_seam() -> None:
    text = "x" * 300

    assert len(render_x_snippet(text)) == 280
    assert render_x_snippet(text, public=True) == "[private snippet hidden]"


def test_overview_tiles_link_to_detail_pages(tmp_path: Path) -> None:
    response = TestClient(create_app(tmp_path / "synthetic.db")).get("/")

    assert "href='/portfolio'" in response.text
    assert "href='/regime'" in response.text
