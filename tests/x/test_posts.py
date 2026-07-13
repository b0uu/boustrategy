import sqlite3
from datetime import UTC, datetime

import pytest

from app.storage.database import connect
from app.x.accounts import Account, upsert_account
from app.x.client import FetchResult
from app.x.posts import (
    XPost,
    insert_new_posts,
    mark_reviewed,
    reads_remaining,
    record_post_reads,
    unreviewed_posts,
    unreviewed_thread_posts,
)
from app.x.run import _cmd_fetch


def make_post(post_id: str = "1", handle: str = "someone") -> XPost:
    return XPost(
        post_id=post_id,
        handle=handle,
        posted_at=datetime(2026, 7, 1, tzinfo=UTC),
        text="hello world",
        url=f"https://x.com/{handle}/status/{post_id}",
        fetched_at=datetime(2026, 7, 1, 1, tzinfo=UTC),
    )


def test_insert_new_posts_ignores_duplicate_post_ids():
    conn = connect(":memory:")
    post = make_post("1")

    first = insert_new_posts(conn, [post])
    second = insert_new_posts(conn, [post, make_post("2")])

    assert first == 1
    assert second == 1


def test_spend_guard_stops_fetch_before_fake_fetcher_is_called():
    conn = connect(":memory:")
    upsert_account(conn, Account(handle="core1", user_id="uid1", tier="core"))
    record_post_reads(conn, 3950)

    assert reads_remaining(conn) < 100

    called = False

    def fake_resolve(handles: list[str]) -> dict[str, str]:
        return {}

    def fake_fetch(user_id: str, handle: str, since_id: str | None) -> FetchResult:
        nonlocal called
        called = True
        return FetchResult(posts=[], billed_reads=0)

    _cmd_fetch(conn, resolve_ids=fake_resolve, fetch_posts=fake_fetch)

    assert called is False


def test_fetch_computes_since_id_numerically_not_lexicographically():
    conn = connect(":memory:")
    upsert_account(conn, Account(handle="core1", user_id="uid1", tier="core"))
    insert_new_posts(
        conn,
        [
            make_post("99999999999", handle="core1"),
            make_post("1900000000000000000", handle="core1"),
        ],
    )

    received_since_ids: list[str | None] = []

    def fake_resolve(handles: list[str]) -> dict[str, str]:
        return {}

    def fake_fetch(user_id: str, handle: str, since_id: str | None) -> FetchResult:
        received_since_ids.append(since_id)
        return FetchResult(posts=[], billed_reads=0)

    _cmd_fetch(conn, resolve_ids=fake_resolve, fetch_posts=fake_fetch)

    assert received_since_ids == ["1900000000000000000"]


def test_mark_reviewed_enforces_unreviewed_to_captured_or_skipped_only():
    conn = connect(":memory:")
    insert_new_posts(conn, [make_post("1")])

    mark_reviewed(conn, "1", "captured")

    with pytest.raises(ValueError):
        mark_reviewed(conn, "1", "skipped")


def test_context_fields_survive_insert_and_unreviewed_posts_round_trip():
    conn = connect(":memory:")
    post = XPost(
        post_id="1",
        handle="someone",
        posted_at=datetime(2026, 7, 1, tzinfo=UTC),
        text="Yes, and TSMC confirmed this",
        url="https://x.com/someone/status/1",
        fetched_at=datetime(2026, 7, 1, 1, tzinfo=UTC),
        conversation_id="100",
        reply_context="TSMC capacity is tight this quarter",
    )

    insert_new_posts(conn, [post])
    fetched = unreviewed_posts(conn)

    assert len(fetched) == 1
    assert fetched[0].conversation_id == "100"
    assert fetched[0].reply_context == "TSMC capacity is tight this quarter"


def test_connect_migrates_old_schema_db_adding_context_columns(tmp_path):
    db_path = tmp_path / "old.db"
    old_conn = sqlite3.connect(db_path)
    old_conn.execute(
        """
        CREATE TABLE x_posts (
            post_id TEXT PRIMARY KEY,
            handle TEXT NOT NULL,
            posted_at TEXT NOT NULL,
            text TEXT NOT NULL,
            url TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            review_status TEXT NOT NULL DEFAULT 'unreviewed'
        )
        """
    )
    old_conn.execute(
        """
        INSERT INTO x_posts (post_id, handle, posted_at, text, url, fetched_at)
        VALUES ('1', 'someone', '2026-07-01T00:00:00+00:00', 'hello',
                'https://x.com/x', '2026-07-01T01:00:00+00:00')
        """
    )
    old_conn.commit()
    old_conn.close()

    conn = connect(db_path)

    row = conn.execute(
        "SELECT post_id, handle, conversation_id, reply_context FROM x_posts WHERE post_id = '1'"
    ).fetchone()
    assert row == ("1", "someone", "", "")


def test_unreviewed_thread_posts_groups_same_handle_same_conversation():
    conn = connect(":memory:")
    insert_new_posts(
        conn,
        [
            make_post("1", handle="someone").model_copy(update={"conversation_id": "100"}),
            make_post("2", handle="someone").model_copy(update={"conversation_id": "100"}),
            make_post("3", handle="someone").model_copy(update={"conversation_id": "200"}),
            make_post("4", handle="other").model_copy(update={"conversation_id": "100"}),
        ],
    )

    thread = unreviewed_thread_posts(conn, "someone", "100", exclude_post_id="1")

    assert [p.post_id for p in thread] == ["2"]


def test_fetch_records_billed_reads_including_included_tweets():
    conn = connect(":memory:")
    upsert_account(conn, Account(handle="core1", user_id="uid1", tier="core"))

    def fake_resolve(handles: list[str]) -> dict[str, str]:
        return {}

    def fake_fetch(user_id: str, handle: str, since_id: str | None) -> FetchResult:
        return FetchResult(posts=[make_post("1"), make_post("2")], billed_reads=3)

    _cmd_fetch(conn, resolve_ids=fake_resolve, fetch_posts=fake_fetch)

    assert reads_remaining(conn) == 4000 - 3


def test_end_to_end_fetch_stores_reply_context_and_review_ui_shows_it(tmp_path):
    """Offline proof that a reply's parent context survives fetch -> storage
    -> review UI, closing the loop this plan exists to fix (plan 012)."""
    from fastapi.testclient import TestClient

    from app.labeling.server import create_app

    db_path = tmp_path / "e2e.db"
    conn = connect(db_path)
    upsert_account(conn, Account(handle="core1", user_id="uid1", tier="core"))

    reply_post = XPost(
        post_id="42",
        handle="core1",
        posted_at=datetime(2026, 7, 1, tzinfo=UTC),
        text="Yes, and TSMC confirmed this",
        url="https://x.com/core1/status/42",
        fetched_at=datetime(2026, 7, 1, 1, tzinfo=UTC),
        conversation_id="10",
        reply_context="TSMC capacity is tight this quarter",
    )

    def fake_resolve(handles: list[str]) -> dict[str, str]:
        return {}

    def fake_fetch(user_id: str, handle: str, since_id: str | None) -> FetchResult:
        return FetchResult(posts=[reply_post], billed_reads=2)

    _cmd_fetch(conn, resolve_ids=fake_resolve, fetch_posts=fake_fetch)
    conn.close()

    client = TestClient(create_app(db_path))
    response = client.get("/api/next")

    assert response.status_code == 200
    body = response.json()
    assert body["post_id"] == "42"
    assert body["reply_context"] == "TSMC capacity is tight this quarter"
