from datetime import UTC, datetime

from app.x.client import _map_tweet
from app.x.posts import MediaItem


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


def test_map_tweet_maps_photo_attachment_into_media():
    fetched_at = datetime(2026, 7, 1, 1, tzinfo=UTC)
    tweet = {
        "id": "6",
        "created_at": "2026-07-01T00:00:00.000Z",
        "text": "chart attached",
        "attachments": {"media_keys": ["3_1"]},
    }
    media_included = {
        "3_1": MediaItem(
            url="https://pbs.twimg.com/media/photo.jpg", media_type="photo", alt_text="a chart"
        ),
    }

    post = _map_tweet(tweet, "someone", fetched_at, media_included=media_included)

    assert len(post.media) == 1
    assert post.media[0].url == "https://pbs.twimg.com/media/photo.jpg"
    assert post.media[0].media_type == "photo"
    assert post.media[0].alt_text == "a chart"


def test_map_tweet_maps_video_attachment_using_preview_image_url():
    fetched_at = datetime(2026, 7, 1, 1, tzinfo=UTC)
    tweet = {
        "id": "7",
        "created_at": "2026-07-01T00:00:00.000Z",
        "text": "video attached",
        "attachments": {"media_keys": ["7_1"]},
    }
    media_included = {
        "7_1": MediaItem(url="https://pbs.twimg.com/preview/vid.jpg", media_type="video"),
    }

    post = _map_tweet(tweet, "someone", fetched_at, media_included=media_included)

    assert len(post.media) == 1
    assert post.media[0].url == "https://pbs.twimg.com/preview/vid.jpg"
    assert post.media[0].media_type == "video"


def test_map_tweet_with_no_attachments_has_empty_media():
    fetched_at = datetime(2026, 7, 1, 1, tzinfo=UTC)
    tweet = {
        "id": "8",
        "created_at": "2026-07-01T00:00:00.000Z",
        "text": "no media here",
    }

    post = _map_tweet(tweet, "someone", fetched_at)

    assert post.media == []


def test_map_media_skips_entry_with_no_usable_url():
    from app.x.client import _map_media

    assert _map_media({"media_key": "x_1", "type": "photo"}) is None


def test_map_media_prefers_url_over_preview_image_url():
    from app.x.client import _map_media

    mapped = _map_media(
        {
            "media_key": "x_1",
            "type": "photo",
            "url": "https://pbs.twimg.com/media/photo.jpg",
            "preview_image_url": "https://pbs.twimg.com/preview/should-not-use.jpg",
        }
    )

    assert mapped is not None
    assert mapped.url == "https://pbs.twimg.com/media/photo.jpg"
