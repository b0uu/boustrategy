import os
from datetime import UTC, datetime

import httpx

from app.x.posts import XPost

BASE_URL = "https://api.x.com/2"
_REQUEST_TIMEOUT = 30.0


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


def fetch_user_posts(user_id: str, handle: str, since_id: str | None = None) -> list[XPost]:
    params: dict[str, str] = {"max_results": "100", "tweet.fields": "created_at,text"}
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

    return [
        XPost(
            post_id=tweet["id"],
            handle=handle,
            posted_at=tweet["created_at"],
            text=tweet["text"],
            url=f"https://x.com/{handle}/status/{tweet['id']}",
            fetched_at=fetched_at,
        )
        for tweet in response.json().get("data", [])
    ]
