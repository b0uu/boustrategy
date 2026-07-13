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


def test_map_tweet_sets_conversation_id_and_reply_context_from_included_parent():
    fetched_at = datetime(2026, 7, 1, 1, tzinfo=UTC)
    tweet = {
        "id": "3",
        "created_at": "2026-07-01T00:00:00.000Z",
        "text": "Yes, and TSMC confirmed this",
        "conversation_id": "100",
        "referenced_tweets": [{"type": "replied_to", "id": "1"}],
    }
    included = {"1": "TSMC capacity is tight this quarter"}

    post = _map_tweet(tweet, "someone", fetched_at, included)

    assert post.conversation_id == "100"
    assert post.reply_context == "TSMC capacity is tight this quarter"


def test_map_tweet_picks_up_reply_context_from_quoted_reference():
    fetched_at = datetime(2026, 7, 1, 1, tzinfo=UTC)
    tweet = {
        "id": "4",
        "created_at": "2026-07-01T00:00:00.000Z",
        "text": "this is exactly right",
        "conversation_id": "200",
        "referenced_tweets": [{"type": "quoted", "id": "9"}],
    }
    included = {"9": "the original quoted post text"}

    post = _map_tweet(tweet, "someone", fetched_at, included)

    assert post.reply_context == "the original quoted post text"


def test_map_tweet_no_references_leaves_context_fields_empty():
    fetched_at = datetime(2026, 7, 1, 1, tzinfo=UTC)
    tweet = {
        "id": "5",
        "created_at": "2026-07-01T00:00:00.000Z",
        "text": "standalone post",
    }

    post = _map_tweet(tweet, "someone", fetched_at)

    assert post.conversation_id == ""
    assert post.reply_context == ""
