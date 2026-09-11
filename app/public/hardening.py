"""Response headers and per-client request limiting for the internet-facing origin.

The origin binds loopback only and is reached through a Cloudflare Tunnel, so every
tunnelled request arrives from a loopback peer. Cloudflare's edge overwrites
``CF-Connecting-IP`` with the real client address, which makes that header the only
per-client identity available; it is trusted solely when the server was told it sits
behind the tunnel and the peer is loopback. Anything else keys on the socket peer.
"""

import ipaddress
import math
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from typing import Any

# The built bundle loads only its own hashed script, stylesheet and fonts, and fetches
# only this origin's API. React writes inline styles through the CSSOM, which
# style-src does not govern, so no 'unsafe-inline' is needed.
CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "font-src 'self'",
        "img-src 'self' data:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors 'none'",
    )
)

# Clipboard write stays at the browser default because the share button uses it.
PERMISSIONS_POLICY = ", ".join(
    f"{feature}=()"
    for feature in (
        "accelerometer",
        "browsing-topics",
        "camera",
        "display-capture",
        "geolocation",
        "gyroscope",
        "magnetometer",
        "microphone",
        "midi",
        "payment",
        "usb",
    )
)

SECURITY_HEADERS: Mapping[str, str] = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": PERMISSIONS_POLICY,
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}

_LOOPBACK = {"127.0.0.1", "::1"}


def client_key(scope: Mapping[str, Any], *, trust_tunnel: bool) -> str:
    """Identify the requesting client for limiting, never trusting a spoofable header."""
    peer = str((scope.get("client") or ("unknown", 0))[0])
    if not trust_tunnel or peer not in _LOOPBACK:
        return peer
    forwarded = [
        value for name, value in scope.get("headers", ()) if name.lower() == b"cf-connecting-ip"
    ]
    if len(forwarded) != 1:
        return peer
    try:
        address = ipaddress.ip_address(forwarded[0].decode("ascii").strip())
    except (UnicodeDecodeError, ValueError):
        return peer
    if address.version == 6:
        # One IPv6 subscriber usually holds a whole /64; keying per address would let
        # a single client rotate past the limit.
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return str(address)


class RateLimiter:
    """Token bucket per client, bounded in size, forgetting clients once refilled."""

    def __init__(
        self,
        *,
        capacity: int = 120,
        per_second: float = 2.0,
        max_clients: int = 4096,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if capacity < 1 or per_second <= 0 or max_clients < 1:
            raise ValueError("rate limiter bounds must be positive")
        self.capacity = capacity
        self.per_second = per_second
        self.max_clients = max_clients
        self._clock = clock
        self._refill_seconds = capacity / per_second
        self._buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._buckets)

    def acquire(self, key: str) -> int:
        """Spend one token; return 0 when allowed, else whole seconds until one is due."""
        with self._lock:
            now = self._clock()
            # Buckets are kept in last-seen order, so the stale ones are at the front.
            while self._buckets:
                oldest = next(iter(self._buckets.values()))
                if now - oldest[1] < self._refill_seconds:
                    break
                self._buckets.popitem(last=False)
            tokens, seen = self._buckets.pop(key, (float(self.capacity), now))
            tokens = min(float(self.capacity), tokens + (now - seen) * self.per_second)
            wait = 0
            if tokens >= 1:
                tokens -= 1
            else:
                wait = max(1, math.ceil((1 - tokens) / self.per_second))
            self._buckets[key] = (tokens, now)
            while len(self._buckets) > self.max_clients:
                self._buckets.popitem(last=False)
            return wait
