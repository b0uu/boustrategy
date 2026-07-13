import os
from datetime import UTC, datetime
from typing import Any, NamedTuple

import httpx

from app.x.posts import MediaItem, XPost

BASE_URL = "https://api.x.com/2"
_REQUEST_TIMEOUT = 30.0


class FetchResult(NamedTuple):
    posts: list[XPost]
    billed_reads: int


def _auth_headers() -> dict[str, str]:
    token = os.environ.get("X_BEARER_TOKEN")
    if not token:
        raise RuntimeError("X_BEARER_TOKEN environment variable is not set")
    return {"Authorization": f"Bearer {token}"}


def resolve_user_ids(handles: list[str]) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for start in range(0, len(handles), 100):
        batch = handles[start : start + 100]
        response = httpx.get(
            f"{BASE_URL}/users/by",
            params={"usernames": ",".join(batch)},
            headers=_auth_headers(),
            timeout=_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        for user in response.json().get("data", []):
            resolved[user["username"].lower()] = user["id"]
    return resolved


def _preferred_text(tweet: dict[str, Any]) -> str:
    note_tweet = tweet.get("note_tweet")
    if note_tweet and note_tweet.get("text"):
        return str(note_tweet["text"])
    return str(tweet["text"])


def _map_media(media: dict[str, Any]) -> MediaItem | None:
    # Photos carry `url`; videos/gifs usually only carry `preview_image_url`
    # (X does not expose direct video file URLs via this endpoint).
    url = media.get("url") or media.get("preview_image_url") or ""
    if not url:
        return None
    return MediaItem(url=url, media_type=media["type"], alt_text=media.get("alt_text", ""))


def _map_tweet(
    tweet: dict[str, Any],
    handle: str,
    fetched_at: datetime,
    included: dict[str, str] | None = None,
    media_included: dict[str, MediaItem] | None = None,
) -> XPost:
    included = included or {}
    media_included = media_included or {}
    text = _preferred_text(tweet)

    conversation_id = tweet.get("conversation_id", "")
    reply_context = ""
    referenced = tweet.get("referenced_tweets") or []
    # Prefer replied_to over quoted when both are present: a reply's own text
    # is meaningless without the parent, whereas a quote at least stands on
    # its own — but an unreviewable quote has the same problem, so fall back
    # to it when there's no reply reference.
    replied_to_id = next((ref["id"] for ref in referenced if ref.get("type") == "replied_to"), None)
    quoted_id = next((ref["id"] for ref in referenced if ref.get("type") == "quoted"), None)
    if replied_to_id is not None and replied_to_id in included:
        reply_context = included[replied_to_id]
    elif quoted_id is not None and quoted_id in included:
        reply_context = included[quoted_id]

    media_keys = (tweet.get("attachments") or {}).get("media_keys") or []
    media = [media_included[key] for key in media_keys if key in media_included]

    return XPost(
        post_id=tweet["id"],
        handle=handle,
        posted_at=tweet["created_at"],
        text=text,
        url=f"https://x.com/{handle}/status/{tweet['id']}",
        fetched_at=fetched_at,
        conversation_id=conversation_id,
        reply_context=reply_context,
        media=media,
    )


def fetch_user_posts(user_id: str, handle: str, since_id: str | None = None) -> FetchResult:
    params: dict[str, str] = {
        "max_results": "100",
        "tweet.fields": "created_at,text,note_tweet,conversation_id,referenced_tweets,attachments",
        "expansions": "referenced_tweets.id,attachments.media_keys",
        "media.fields": "media_key,type,url,preview_image_url,alt_text",
    }
    if since_id is not None:
        params["since_id"] = since_id

    response = httpx.get(
        f"{BASE_URL}/users/{user_id}/tweets",
        params=params,
        headers=_auth_headers(),
        timeout=_REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    fetched_at = datetime.now(UTC)

    body = response.json()
    data = body.get("data", [])
    included_tweets = body.get("includes", {}).get("tweets", [])
    included = {tweet["id"]: _preferred_text(tweet) for tweet in included_tweets}
    included_media = body.get("includes", {}).get("media", [])
    media_included: dict[str, MediaItem] = {}
    for media in included_media:
        mapped = _map_media(media)
        if mapped is not None:
            media_included[media["media_key"]] = mapped

    posts = [_map_tweet(tweet, handle, fetched_at, included, media_included) for tweet in data]
    # Media objects are not posts and are not separately billed by the API —
    # only tweet-shaped objects (data + included tweets) count toward reads.
    billed_reads = len(data) + len(included_tweets)
    return FetchResult(posts=posts, billed_reads=billed_reads)
