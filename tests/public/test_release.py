import json
import shutil
import sqlite3
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from urllib.parse import quote
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.public.database import open_readonly
from app.public.publication import publish, revoke
from app.public.queries import feed
from app.public.server import create_public_app
from app.schemas.decision_record import InvestmentDecisionRecord
from app.state.pipeline import process_decision
from app.storage.database import connect
from tests.fixtures.decision_records import valid_decision_record_data
from tests.public.test_public_v2 import seed


def test_built_public_surface_has_no_mutation_routes_and_reads_write_nothing(
    tmp_path: Path,
) -> None:
    source, public = tmp_path / "source.db", tmp_path / "public.db"
    assets = tmp_path / "ui"
    (assets / "assets").mkdir(parents=True)
    (assets / "index.html").write_text("<html>public shell</html>", encoding="utf-8")
    (assets / "assets" / "app.js").write_text("export {}", encoding="utf-8")
    seed(source, count=1)
    publish(source, public)
    app = create_public_app(public, assets)
    client = TestClient(app)
    item = client.get("/api/public/v2/decisions?portfolio_id=paper").json()["items"][0]
    legacy = f"{item['ticker']}/{quote(item['created_at'], safe='')}"
    api_urls = [
        "/api/public/v1/dashboard",
        f"/api/public/v1/decisions/{legacy}",
        "/api/public/v2/portfolios",
        "/api/public/v2/portfolios/live/overview",
        "/api/public/v2/portfolios/live/runtime",
        "/api/public/v2/portfolios/live/activity",
        "/api/public/v2/portfolios/live/positions",
        "/api/public/v2/portfolios/live/performance?range=All",
        "/api/public/v2/portfolios/live/policy",
        "/api/public/v2/decisions?portfolio_id=paper",
        f"/api/public/v2/decisions/{item['public_id']}",
        f"/api/public/v2/decisions/{item['public_id']}/export?format=json",
        f"/api/public/v2/decisions/{item['public_id']}/export?format=csv",
        f"/api/public/v2/legacy-decisions/{legacy}",
    ]
    before = (source.read_bytes(), public.read_bytes())

    for route in app.routes:
        methods = getattr(route, "methods", None)
        if getattr(route, "path", "").startswith("/api/") and methods:
            assert not methods & {"POST", "PUT", "PATCH", "DELETE"}
    for url in api_urls:
        response = client.get(url)
        assert response.status_code == 200, url
        assert response.headers["cache-control"] == "no-store"
        head = client.head(url)
        assert head.status_code == 200, url
        assert not head.content
        assert head.headers["cache-control"] == "no-store"
    for method in ("post", "put", "patch", "delete"):
        assert getattr(client, method)("/api/public/v2/decisions").status_code == 405

    assert client.get("/").text == "<html>public shell</html>"
    assert client.get(f"/decisions/{item['public_id']}").status_code == 200
    assert client.get("/assets/app.js").status_code == 200
    for url in (
        "/api/public/v2/unknown/private-sentinel",
        "/assets/missing.js",
        "/private-sentinel",
    ):
        response = client.get(url)
        assert response.status_code == 404
        assert "private-sentinel" not in response.text
    assert before == (source.read_bytes(), public.read_bytes())
    assert not Path(str(public) + "-wal").exists()
    assert not Path(str(public) + "-shm").exists()


def test_compression_preserves_public_payload_and_no_store(tmp_path: Path) -> None:
    source, public = tmp_path / "source.db", tmp_path / "public.db"
    seed(source, count=2)
    publish(source, public)
    client = TestClient(create_public_app(public))
    url = "/api/public/v2/decisions?portfolio_id=paper"

    plain = client.get(url, headers={"Accept-Encoding": "identity"})
    compressed = client.get(url, headers={"Accept-Encoding": "gzip"})

    assert compressed.status_code == plain.status_code == 200
    assert compressed.headers["content-encoding"] == "gzip"
    assert compressed.headers["cache-control"] == "no-store"
    assert "Accept-Encoding" in compressed.headers["vary"]
    assert int(compressed.headers["content-length"]) < len(plain.content)
    assert compressed.json()["items"] == plain.json()["items"]


def test_publication_failure_rolls_back_and_retry_keeps_public_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, public = tmp_path / "source.db", tmp_path / "public.db"
    seed(source, count=2)
    publish(source, public)
    with open_readonly(public) as reader:
        original = feed(reader, portfolio_id="paper")["items"][0]
        checkpoint = reader.execute(
            "SELECT content FROM publication_checkpoint WHERE singleton=1"
        ).fetchone()[0]
    conn = connect(source)
    conn.execute(
        "UPDATE decision_records SET record_json=json_set(record_json, "
        "'$.public_summary', 'Recovered public summary')"
    )
    conn.commit()
    conn.close()
    real_validate = InvestmentDecisionRecord.model_validate_json
    validations = 0

    def interrupted(value: str) -> InvestmentDecisionRecord:
        nonlocal validations
        validations += 1
        if validations == 2:
            raise RuntimeError("synthetic_publication_interruption")
        return real_validate(value)

    monkeypatch.setattr(InvestmentDecisionRecord, "model_validate_json", interrupted)
    with pytest.raises(RuntimeError, match="synthetic_publication_interruption"):
        publish(source, public)
    with open_readonly(public) as reader:
        after_failure = feed(reader, portfolio_id="paper")["items"][0]
        assert after_failure == original
        assert (
            reader.execute(
                "SELECT content FROM publication_checkpoint WHERE singleton=1"
            ).fetchone()[0]
            == checkpoint
        )

    monkeypatch.setattr(InvestmentDecisionRecord, "model_validate_json", real_validate)
    assert publish(source, public)["updated"] == 2
    with open_readonly(public) as reader:
        recovered = feed(reader, portfolio_id="paper")["items"][0]
    assert recovered["public_id"] == original["public_id"]
    assert recovered["public_summary"] == "Recovered public summary"


def test_readers_keep_a_consistent_snapshot_during_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, public = tmp_path / "source.db", tmp_path / "public.db"
    seed(source, count=20)
    publish(source, public)
    conn = connect(source)
    conn.execute(
        "UPDATE decision_records SET record_json=json_set(record_json, "
        "'$.public_summary', 'New published version') WHERE decision_id='private_0'"
    )
    conn.commit()
    conn.close()
    transaction_open = Event()
    release = Event()
    real_validate = InvestmentDecisionRecord.model_validate_json

    def paused_validation(value: str) -> InvestmentDecisionRecord:
        transaction_open.set()
        assert release.wait(10)
        return real_validate(value)

    monkeypatch.setattr(InvestmentDecisionRecord, "model_validate_json", paused_validation)
    app = create_public_app(public, tmp_path / "no-ui")

    def read_snapshot() -> tuple[int, int, str]:
        response = TestClient(app).get(
            "/api/public/v2/decisions", params={"portfolio_id": "paper", "limit": 25}
        )
        payload = response.json()
        return response.status_code, payload["total"], json.dumps(payload)

    with ThreadPoolExecutor(max_workers=9) as pool:
        writing = pool.submit(publish, source, public)
        assert transaction_open.wait(10)
        reading = [pool.submit(read_snapshot) for _ in range(8)]
        try:
            snapshots = [future.result(timeout=5) for future in reading]
        finally:
            release.set()
        assert writing.result(timeout=10)["updated"] == 1

    assert all(status == 200 and total == 20 for status, total, _ in snapshots)
    assert all("New published version" not in payload for _, _, payload in snapshots)
    assert read_snapshot()[0:2] == (200, 20)
    assert "New published version" in read_snapshot()[2]


def test_materialized_overview_counts_are_bounded_current_and_retraction_aware(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, public = tmp_path / "source.db", tmp_path / "public.db"
    conn = connect(source)
    now = datetime.now(UTC)
    for index in range(2):
        record = valid_decision_record_data()
        record.update(decision_id=f"today_{index}", created_at=now - timedelta(seconds=index))
        process_decision(conn, record, received_at=record["created_at"])
    conn.close()
    publish(source, public)
    client = TestClient(create_public_app(public))
    overview = client.get("/api/public/v2/portfolios/paper/overview").json()
    item = client.get("/api/public/v2/decisions?portfolio_id=paper").json()["items"][0]
    assert overview["decision_counts"] == {
        "approved": 2,
        "rejected": 0,
        "unavailable": 0,
    }
    assert overview["decisions_today"] == 2
    with open_readonly(public) as reader:
        stored = json.loads(
            reader.execute(
                "SELECT content FROM public_portfolios WHERE portfolio_id='paper'"
            ).fetchone()[0]
        )
    assert stored["decision_counts"] == overview["decision_counts"]
    new_york = ZoneInfo("America/New_York")
    assert stored["decision_count_date"] == now.astimezone(new_york).date().isoformat()
    assert stored["decisions_today"] == 2

    assert revoke(public, item["public_id"])
    overview = client.get("/api/public/v2/portfolios/paper/overview").json()
    assert overview["decision_counts"] == {
        "approved": 1,
        "rejected": 0,
        "unavailable": 0,
    }
    assert overview["decisions_today"] == 1

    real_open = open_readonly

    @contextmanager
    def deny_decision_reads(path: str | Path) -> Iterator[sqlite3.Connection]:
        with real_open(path) as reader:

            def authorize(
                action: int,
                table: str | None,
                column: str | None,
                database: str | None,
                trigger: str | None,
            ) -> int:
                del column, database, trigger
                if action == sqlite3.SQLITE_READ and table == "public_decisions":
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK

            reader.set_authorizer(authorize)
            yield reader

    monkeypatch.setattr("app.public.server.open_readonly", deny_decision_reads)
    assert client.get("/api/public/v2/portfolios/paper/overview").status_code == 200
    monkeypatch.setattr("app.public.server.open_readonly", real_open)

    conn = sqlite3.connect(public)
    yesterday = (now - timedelta(days=1)).astimezone(new_york).date().isoformat()
    conn.execute(
        "UPDATE public_portfolios SET content=json_set(content, "
        "'$.decision_count_date', ?, '$.decisions_today', 99) WHERE portfolio_id='paper'",
        (yesterday,),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr("app.public.server.open_readonly", deny_decision_reads)
    assert client.get("/api/public/v2/portfolios/paper/overview").json()["decisions_today"] == 0
    monkeypatch.setattr("app.public.server.open_readonly", real_open)

    old_public = tmp_path / "old-public.db"
    shutil.copyfile(public, old_public)
    conn = sqlite3.connect(old_public)
    raw = conn.execute(
        "SELECT content FROM public_portfolios WHERE portfolio_id='paper'"
    ).fetchone()[0]
    old_portfolio = json.loads(raw)
    for key in ("decision_counts", "decision_count_date", "decisions_today"):
        old_portfolio.pop(key, None)
    conn.execute(
        "UPDATE public_portfolios SET content=? WHERE portfolio_id='paper'",
        (json.dumps(old_portfolio, sort_keys=True),),
    )
    conn.commit()
    conn.close()
    fallback = TestClient(create_public_app(old_public)).get(
        "/api/public/v2/portfolios/paper/overview"
    )
    assert fallback.status_code == 200
    assert fallback.json()["decision_counts"]["approved"] == 1
    assert fallback.json()["decisions_today"] == 1
