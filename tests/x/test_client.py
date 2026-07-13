from datetime import UTC, datetime

from app.x.client import _map_tweet


def test_map_tweet_uses_text_field_when_no_note_tweet():
    fetched_at = datetime(2026, 7, 1, 1, tzinfo=UTC)
    tweet = {
        "id": "1",
        "created_at": "2026-07-01T00:00:00.000Z",
        "text": "hello world",
    }

    post = _map_tweet(tweet, "someone", fetched_at)

    assert post.text == "hello world"
    assert post.post_id == "1"
    assert post.url == "https://x.com/someone/status/1"


def test_map_tweet_prefers_note_tweet_text_when_present():
    fetched_at = datetime(2026, 7, 1, 1, tzinfo=UTC)
    long_text = "a" * 5000
    tweet = {
        "id": "2",
        "created_at": "2026-07-01T00:00:00.000Z",
        "text": "hello world (truncated)…",
        "note_tweet": {"text": long_text},
    }

    post = _map_tweet(tweet, "someone", fetched_at)

    assert post.text == long_text
