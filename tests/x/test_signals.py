from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.storage.database import connect
from app.x.posts import XPost, insert_new_posts
from app.x.signals import CapturedSignal, save_signal


def make_post() -> XPost:
    return XPost(
        post_id="1",
        handle="someone",
        posted_at=datetime(2026, 7, 1, tzinfo=UTC),
        text="hello world",
        url="https://x.com/someone/status/1",
        fetched_at=datetime(2026, 7, 1, 1, tzinfo=UTC),
    )


def make_signal(**overrides: object) -> CapturedSignal:
    data: dict[str, object] = {
        "entry_id": "xs_1",
        "post_id": "1",
        "captured_at": datetime(2026, 7, 1, 2, tzinfo=UTC),
        "post_url": "https://x.com/someone/status/1",
        "handle": "someone",
        "posted_at": datetime(2026, 7, 1, tzinfo=UTC),
        "primary_theme_id": "ai_semiconductors",
        "tickers": ["NVDA"],
        "claim": "some claim",
        "claim_type": "fact",
        "stance": "idea_source",
        "horizon": "short",
        "scrutiny_verdict": "substantiated",
        "why_it_matters": "it matters",
    }
    data.update(overrides)
    return CapturedSignal.model_validate(data)


def test_save_signal_round_trips_and_marks_post_captured():
    conn = connect(":memory:")
    insert_new_posts(conn, [make_post()])
    signal = make_signal()

    first = save_signal(conn, signal)
    review_status = conn.execute(
        "SELECT review_status FROM x_posts WHERE post_id = ?", ("1",)
    ).fetchone()[0]

    assert first is True
    assert review_status == "captured"

    second = save_signal(conn, signal)
    assert second is False


def test_conflicting_signal_content_under_same_entry_id_raises():
    conn = connect(":memory:")
    insert_new_posts(conn, [make_post()])
    save_signal(conn, make_signal())

    with pytest.raises(ValueError):
        save_signal(conn, make_signal(claim="a different claim"))


def test_captured_signal_rejects_unknown_stance_or_verdict():
    with pytest.raises(ValidationError):
        make_signal(stance="not_a_real_stance")

    with pytest.raises(ValidationError):
        make_signal(scrutiny_verdict="not_a_real_verdict")
