import json
import re
import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.dashboard.queries import overview, x_data
from app.dashboard.server import create_app
from app.reason.run import PreparationResult
from app.schemas.decision_record import RegimeState
from app.storage.database import connect

ROUTES = (
    "/",
    "/operate",
    "/operate/live",
    "/portfolio",
    "/decisions",
    "/executions",
    "/digests",
    "/x",
    "/regime",
    "/triggers",
    "/operations",
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

    assert post_routes == [
        "/operate/prepare",
        "/operations/task",
        "/operations/schedule",
        "/operations/attempt",
    ]


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
    assert "This is the close paper reasoning pass" in response.text
    assert "Treat missing outside-X confirmation as a research task" in response.text
    assert "Don&#x27;t resubmit an existing decision record" in response.text
    assert "never a future timestamp" in response.text


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


def test_overview_tiles_link_to_detail_pages(tmp_path: Path) -> None:
    response = TestClient(create_app(tmp_path / "synthetic.db")).get("/")

    assert "href='/portfolio'" in response.text
    assert "href='/regime'" in response.text
    assert "href='/executions'" in response.text


def test_portfolio_shows_paper_intent_and_executions_remain_disabled(tmp_path: Path) -> None:
    db_path = tmp_path / "synthetic.db"
    conn = connect(db_path)
    conn.execute(
        """
        INSERT INTO order_intents
            (order_intent_id, decision_id, created_at, ticker, side, execution_mode, intent_json)
        VALUES ('oi_1', 'dec_1', '2026-08-26T12:00:00Z', 'NVDA', 'BUY', 'PAPER', '{}')
        """
    )
    conn.commit()
    client = TestClient(create_app(db_path))

    portfolio = client.get("/portfolio")
    executions = client.get("/executions")

    assert "awaiting_price" in portfolio.text
    assert "PAPER" in portfolio.text
    assert "Dashboard placement is disabled" in executions.text
    assert "data-copy='execution-prompt' disabled" in executions.text


def test_execution_page_shows_public_profile_limits_without_credentials(tmp_path: Path) -> None:
    config_path = tmp_path / "live.json"
    config_path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "execution_profile_id": "codex",
                        "agent_provider": "CODEX",
                        "account_alias": "codex-agentic",
                        "enabled": False,
                        "max_order_notional": 20.0,
                        "max_quote_age_seconds": 60,
                        "max_spread_bps": 50.0,
                        "require_human_approval": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(create_app(tmp_path / "synthetic.db", live_config_path=config_path))

    response = client.get("/executions")

    assert "codex-agentic" in response.text
    assert "20.00" in response.text


def _write_live_config(path: Path, *, enabled: bool) -> Path:
    path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "execution_profile_id": "codex",
                        "agent_provider": "CODEX",
                        "account_alias": "codex-agentic",
                        "broker_account_fingerprint": ("0123456789abcdef" if enabled else ""),
                        "enabled": enabled,
                        "max_order_notional": 20.0,
                        "max_quote_age_seconds": 60,
                        "max_spread_bps": 50.0,
                        "require_human_approval": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def _insert_execution_packet(
    db_path: Path, *, expires_at: datetime, executed: bool = False
) -> None:
    conn = connect(db_path)
    conn.execute(
        """
        INSERT INTO live_execution_packets
            (execution_packet_id, order_intent_id, execution_profile_id, created_at,
             expires_at, ticker, side, notional, limit_price, packet_json)
        VALUES ('ep_1', 'oi_1', 'codex', ?, ?, 'NVDA', 'BUY', 12.0, 200.0, '{}')
        """,
        ((expires_at - timedelta(seconds=10)).isoformat(), expires_at.isoformat()),
    )
    if executed:
        conn.execute(
            """
            INSERT INTO broker_execution_records
                (broker_execution_record_id, order_intent_id, execution_packet_id,
                 execution_profile_id, account_alias, submitted_at, ticker, side,
                 status, broker_order_id, record_json)
            VALUES ('ber_1', 'oi_1', 'ep_1', 'codex', 'codex-agentic', ?, 'NVDA',
                    'BUY', 'SUBMITTED', 'rh_1', '{}')
            """,
            (datetime.now(UTC).isoformat(),),
        )
    conn.commit()


def test_execution_prompt_is_enabled_for_current_unexecuted_packet(tmp_path: Path) -> None:
    db_path = tmp_path / "synthetic.db"
    _insert_execution_packet(db_path, expires_at=datetime.now(UTC) + timedelta(minutes=1))
    config_path = _write_live_config(tmp_path / "live.json", enabled=True)

    response = TestClient(create_app(db_path, live_config_path=config_path)).get("/executions")

    assert "data-copy='execution-prompt' disabled" not in response.text


def test_execution_prompt_is_disabled_for_expired_packet(tmp_path: Path) -> None:
    db_path = tmp_path / "synthetic.db"
    _insert_execution_packet(db_path, expires_at=datetime.now(UTC) - timedelta(minutes=1))
    config_path = _write_live_config(tmp_path / "live.json", enabled=True)

    response = TestClient(create_app(db_path, live_config_path=config_path)).get("/executions")

    assert "data-copy='execution-prompt' disabled" in response.text


def test_execution_prompt_is_disabled_for_executed_packet(tmp_path: Path) -> None:
    db_path = tmp_path / "synthetic.db"
    _insert_execution_packet(
        db_path, expires_at=datetime.now(UTC) + timedelta(minutes=1), executed=True
    )
    config_path = _write_live_config(tmp_path / "live.json", enabled=True)

    response = TestClient(create_app(db_path, live_config_path=config_path)).get("/executions")

    assert "data-copy='execution-prompt' disabled" in response.text


def test_execution_prompt_is_disabled_for_disabled_profile(tmp_path: Path) -> None:
    db_path = tmp_path / "synthetic.db"
    _insert_execution_packet(db_path, expires_at=datetime.now(UTC) + timedelta(minutes=1))
    config_path = _write_live_config(tmp_path / "live.json", enabled=False)

    response = TestClient(create_app(db_path, live_config_path=config_path)).get("/executions")

    assert "data-copy='execution-prompt' disabled" in response.text
