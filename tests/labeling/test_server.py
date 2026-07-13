from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.labeling.server import create_app
from app.storage.database import connect
from app.x.posts import XPost, insert_new_posts


def make_post(post_id: str, handle: str = "someone", *, posted_at: datetime) -> XPost:
    return XPost(
        post_id=post_id,
        handle=handle,
        posted_at=posted_at,
        text=f"post {post_id}",
        url=f"https://x.com/{handle}/status/{post_id}",
        fetched_at=datetime(2026, 7, 1, tzinfo=UTC),
    )


def seed(db_path: Path, posts: list[XPost]) -> None:
    conn = connect(str(db_path))
    insert_new_posts(conn, posts)
    conn.close()


def test_next_returns_oldest_unreviewed(tmp_path: Path) -> None:
    db_path = tmp_path / "labeling.db"
    seed(
        db_path,
        [
            make_post("2", posted_at=datetime(2026, 7, 2, tzinfo=UTC)),
            make_post("1", posted_at=datetime(2026, 7, 1, tzinfo=UTC)),
        ],
    )
    client = TestClient(create_app(db_path))

    response = client.get("/api/next")

    assert response.status_code == 200
    body = response.json()
    assert body["empty"] is False
    assert body["post_id"] == "1"
    assert body["remaining"] == 2


def test_skip_marks_and_advances(tmp_path: Path) -> None:
    db_path = tmp_path / "labeling.db"
    seed(
        db_path,
        [
            make_post("1", posted_at=datetime(2026, 7, 1, tzinfo=UTC)),
            make_post("2", posted_at=datetime(2026, 7, 2, tzinfo=UTC)),
        ],
    )
    client = TestClient(create_app(db_path))

    response = client.post("/api/skip", json={"post_id": "1"})

    assert response.status_code == 200
    body = response.json()
    assert body["post_id"] == "2"

    conn = connect(str(db_path))
    status = conn.execute("SELECT review_status FROM x_posts WHERE post_id = ?", ("1",)).fetchone()[
        0
    ]
    conn.close()
    assert status == "skipped"


def _capture_body(post_id: str) -> dict[str, object]:
    return {
        "post_id": post_id,
        "primary_theme_id": "ai_infrastructure",
        "tickers": ["NVDA"],
        "claim": "capacity is tight",
        "claim_type": "fact",
        "stance": "idea_source",
        "horizon": "short",
        "scrutiny_verdict": "substantiated",
        "why_it_matters": "confirms thesis",
    }


def test_capture_saves_signal_and_marks_post(tmp_path: Path) -> None:
    db_path = tmp_path / "labeling.db"
    seed(db_path, [make_post("1", posted_at=datetime(2026, 7, 1, tzinfo=UTC))])
    client = TestClient(create_app(db_path))

    response = client.post("/api/capture", json=_capture_body("1"))

    assert response.status_code == 200
    body = response.json()
    assert body["empty"] is True

    conn = connect(str(db_path))
    signal_row = conn.execute(
        "SELECT entry_id FROM x_signals WHERE entry_id = ?", ("xs_1",)
    ).fetchone()
    post_status = conn.execute(
        "SELECT review_status FROM x_posts WHERE post_id = ?", ("1",)
    ).fetchone()[0]
    conn.close()
    assert signal_row is not None
    assert post_status == "captured"


def test_capture_rejects_unknown_enum_value(tmp_path: Path) -> None:
    db_path = tmp_path / "labeling.db"
    seed(db_path, [make_post("1", posted_at=datetime(2026, 7, 1, tzinfo=UTC))])
    client = TestClient(create_app(db_path))

    body = _capture_body("1")
    body["stance"] = "vibes"
    response = client.post("/api/capture", json=body)

    assert response.status_code == 422

    conn = connect(str(db_path))
    status = conn.execute("SELECT review_status FROM x_posts WHERE post_id = ?", ("1",)).fetchone()[
        0
    ]
    conn.close()
    assert status == "unreviewed"


def test_empty_queue_state(tmp_path: Path) -> None:
    db_path = tmp_path / "labeling.db"
    seed(db_path, [])
    client = TestClient(create_app(db_path))

    api_response = client.get("/api/next")
    assert api_response.status_code == 200
    assert api_response.json()["empty"] is True

    page_response = client.get("/")
    assert page_response.status_code == 200
    assert "No more posts to review" in page_response.text


def test_capture_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "labeling.db"
    seed(db_path, [make_post("1", posted_at=datetime(2026, 7, 1, tzinfo=UTC))])
    client = TestClient(create_app(db_path))

    first = client.post("/api/capture", json=_capture_body("1"))
    assert first.status_code == 200

    conn = connect(str(db_path))
    post_status = conn.execute(
        "SELECT review_status FROM x_posts WHERE post_id = ?", ("1",)
    ).fetchone()[0]
    conn.close()
    assert post_status == "captured"

    second = client.post("/api/capture", json=_capture_body("1"))
    assert second.status_code == 200

    conn = connect(str(db_path))
    signal_count = conn.execute(
        "SELECT COUNT(*) FROM x_signals WHERE entry_id = ?", ("xs_1",)
    ).fetchone()[0]
    conn.close()
    assert signal_count == 1
