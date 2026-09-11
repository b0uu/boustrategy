import sqlite3
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.public.hardening import SECURITY_HEADERS, RateLimiter, client_key
from app.public.publication import publish
from app.public.server import create_public_app
from tests.public.test_public_v2 import seed


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def published(tmp_path: Path) -> tuple[Path, Path]:
    source, public = tmp_path / "source.db", tmp_path / "public.db"
    seed(source, count=1)
    publish(source, public)
    assets = tmp_path / "ui"
    (assets / "assets").mkdir(parents=True)
    (assets / "index.html").write_text("<html>public shell</html>", encoding="utf-8")
    (assets / "assets" / "app-abc123.js").write_text("export {}", encoding="utf-8")
    return public, assets


def assert_hardened(response: httpx.Response) -> None:
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value
    # Cloudflare terminates TLS and owns HSTS; the plain-HTTP origin must not claim it.
    assert "strict-transport-security" not in response.headers


def scope(peer: str, *headers: tuple[bytes, bytes]) -> dict[str, object]:
    return {"client": (peer, 40000), "headers": list(headers)}


def test_every_response_kind_carries_the_security_headers(tmp_path: Path) -> None:
    public, assets = published(tmp_path)
    client = TestClient(create_public_app(public, assets))

    html = client.get("/")
    api = client.get("/api/public/v2/portfolios/live/overview")
    asset = client.get("/assets/app-abc123.js")
    missing_page = client.get("/private-sentinel")
    missing_api = client.get("/api/public/v2/private-sentinel")
    missing_asset = client.get("/assets/missing.js")

    assert (html.status_code, api.status_code, asset.status_code) == (200, 200, 200)
    assert missing_page.status_code == missing_api.status_code == missing_asset.status_code == 404
    for response in (html, api, asset, missing_page, missing_api, missing_asset):
        assert_hardened(response)
    assert api.headers["cache-control"] == missing_api.headers["cache-control"] == "no-store"
    assert html.headers["cache-control"] == "no-cache"
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert "immutable" not in missing_asset.headers.get("cache-control", "")
    assert "frame-ancestors 'none'" in html.headers["content-security-policy"]
    assert "unsafe-inline" not in html.headers["content-security-policy"]


def test_store_failures_answer_503_with_headers_and_no_detail(tmp_path: Path) -> None:
    public, assets = published(tmp_path)
    public.write_bytes(b"not a database, private-sentinel " * 64)
    client = TestClient(create_public_app(public, assets))

    for url in ("/api/public/v2/portfolios/live/overview", "/api/public/v2/health"):
        response = client.get(url)
        assert response.status_code == 503
        assert response.headers["retry-after"] == "30"
        assert response.headers["cache-control"] == "no-store"
        assert "private-sentinel" not in response.text
        assert str(tmp_path) not in response.text
        assert_hardened(response)
    assert client.get("/api/public/v2/health").json() == {"status": "unavailable"}


def test_health_reports_only_status_revision_and_age_when_current(tmp_path: Path) -> None:
    public, assets = published(tmp_path)
    before = public.read_bytes()
    client = TestClient(create_public_app(public, assets))

    response = client.get("/api/public/v2/health")
    head = client.head("/api/public/v2/health")

    assert response.status_code == head.status_code == 200
    body = response.json()
    assert set(body) == {"status", "api_version", "revision", "published_at", "age_seconds"}
    assert body["status"] == "ok"
    assert body["api_version"] == 2
    assert 0 <= body["age_seconds"] < 60
    assert not head.content
    assert public.read_bytes() == before
    assert not Path(f"{public}-wal").exists() and not Path(f"{public}-shm").exists()
    assert not Path(f"{public}-journal").exists()


def test_health_turns_503_when_publication_stops_stamping(tmp_path: Path) -> None:
    public, assets = published(tmp_path)
    conn = sqlite3.connect(public)
    conn.execute("UPDATE publication_meta SET updated_at='2020-01-01T00:00:00+00:00'")
    conn.commit()
    conn.close()

    stale = TestClient(create_public_app(public, assets)).get("/api/public/v2/health")
    fresh = TestClient(create_public_app(public, assets, stale_after_seconds=10**10)).get(
        "/api/public/v2/health"
    )

    assert stale.status_code == 503
    assert stale.json()["status"] == "stale"
    assert stale.headers["retry-after"] == "30"
    assert fresh.status_code == 200


@pytest.mark.parametrize("state", ["missing", "unstamped", "wal"])
def test_health_is_unavailable_for_unusable_stores(tmp_path: Path, state: str) -> None:
    public, assets = published(tmp_path)
    if state == "missing":
        public.unlink()
    else:
        conn = sqlite3.connect(public)
        if state == "unstamped":
            conn.execute("UPDATE publication_meta SET updated_at=''")
        else:
            conn.execute("PRAGMA journal_mode=WAL")
        conn.commit()
        conn.close()

    response = TestClient(create_public_app(public, assets)).get("/api/public/v2/health")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    if state == "missing":
        assert not public.exists()


def test_limiter_allows_a_burst_then_answers_429_until_refilled(tmp_path: Path) -> None:
    public, assets = published(tmp_path)
    clock = Clock()
    limiter = RateLimiter(capacity=3, per_second=0.5, clock=clock)
    client = TestClient(create_public_app(public, assets, limiter=limiter))
    url = "/api/public/v2/portfolios/live/overview"
    before = public.read_bytes()

    assert [client.get(url).status_code for _ in range(3)] == [200, 200, 200]
    limited = client.get(url)
    assert limited.status_code == 429
    assert limited.json() == {"detail": "rate_limited"}
    assert limited.headers["retry-after"] == "2"
    assert limited.headers["cache-control"] == "no-store"
    assert_hardened(limited)
    # The shell and its assets are not limited, so a throttled reader still gets a page.
    assert client.get("/").status_code == 200

    clock.now += 2
    assert client.get(url).status_code == 200
    assert client.get(url).status_code == 429
    assert public.read_bytes() == before


def test_limiter_state_is_bounded_and_forgets_refilled_clients() -> None:
    clock = Clock()
    limiter = RateLimiter(capacity=2, per_second=1, max_clients=3, clock=clock)

    for index in range(10):
        assert limiter.acquire(f"198.51.100.{index}") == 0
    assert len(limiter) == 3

    limiter.acquire("203.0.113.9")
    limiter.acquire("203.0.113.9")
    assert limiter.acquire("203.0.113.9") == 1
    clock.now += 2
    limiter.acquire("203.0.113.10")
    assert len(limiter) == 1
    assert limiter.acquire("203.0.113.9") == 0

    with pytest.raises(ValueError):
        RateLimiter(capacity=0)


def test_client_key_trusts_the_cloudflare_header_only_through_the_tunnel() -> None:
    header = (b"cf-connecting-ip", b"203.0.113.7")

    assert client_key(scope("127.0.0.1", header), trust_tunnel=False) == "127.0.0.1"
    assert client_key(scope("198.51.100.2", header), trust_tunnel=True) == "198.51.100.2"
    assert client_key(scope("127.0.0.1", header), trust_tunnel=True) == "203.0.113.7"
    assert client_key(scope("::1", header), trust_tunnel=True) == "203.0.113.7"
    assert client_key(scope("127.0.0.1"), trust_tunnel=True) == "127.0.0.1"
    spoofed = (b"cf-connecting-ip", b"203.0.113.8")
    assert client_key(scope("127.0.0.1", header, spoofed), trust_tunnel=True) == "127.0.0.1"
    for bad in (b"not-an-ip", b"203.0.113.7, 10.0.0.1", b"\xff"):
        garbage = (b"cf-connecting-ip", bad)
        assert client_key(scope("127.0.0.1", garbage), trust_tunnel=True) == "127.0.0.1"
    v6 = (b"CF-Connecting-IP", b"2001:db8:1:2:3:4:5:6")
    assert client_key(scope("127.0.0.1", v6), trust_tunnel=True) == "2001:db8:1:2::/64"


def test_tunnelled_clients_get_separate_allowances(tmp_path: Path) -> None:
    public, assets = published(tmp_path)
    limiter = RateLimiter(capacity=1, per_second=0.01, clock=Clock())
    app = create_public_app(public, assets, trust_tunnel=True, limiter=limiter)
    client = TestClient(app, client=("127.0.0.1", 50000))
    url = "/api/public/v2/health"

    first = client.get(url, headers={"CF-Connecting-IP": "203.0.113.1"})
    second = client.get(url, headers={"CF-Connecting-IP": "203.0.113.2"})
    repeat = client.get(url, headers={"CF-Connecting-IP": "203.0.113.1"})

    assert (first.status_code, second.status_code, repeat.status_code) == (200, 200, 429)
