from datetime import UTC, datetime

import pytest

from app.storage.database import connect
from app.x.accounts import Account, upsert_account
from app.x.posts import (
    XPost,
    insert_new_posts,
    mark_reviewed,
    reads_remaining,
    record_post_reads,
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

    def fake_fetch(user_id: str, handle: str, since_id: str | None) -> list[XPost]:
        nonlocal called
        called = True
        return []

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

    def fake_fetch(user_id: str, handle: str, since_id: str | None) -> list[XPost]:
        received_since_ids.append(since_id)
        return []

    _cmd_fetch(conn, resolve_ids=fake_resolve, fetch_posts=fake_fetch)

    assert received_since_ids == ["1900000000000000000"]


def test_mark_reviewed_enforces_unreviewed_to_captured_or_skipped_only():
    conn = connect(":memory:")
    insert_new_posts(conn, [make_post("1")])

    mark_reviewed(conn, "1", "captured")

    with pytest.raises(ValueError):
        mark_reviewed(conn, "1", "skipped")
