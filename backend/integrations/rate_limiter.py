"""backend.integrations.rate_limiter — sliding-window per-service limits.

Keeps outbound API pressure comfortably inside each platform's quota so a
busy cycle never trips a platform-side ban:

    meta      10 req/s   (platform allows ~50/s)
    tiktok    30 req/min  (platform allows ~100/min)
    shopify    1 req/s    (platform allows 2/s on the REST API)

Thread-safe.  ``acquire(service)`` blocks (briefly) until a slot frees; in
dry-run nothing ever calls it fast enough to block, so it costs nothing.

    from backend.integrations.rate_limiter import rate_limiter
    rate_limiter.acquire("meta")
    requests.post(...)
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque

_log = logging.getLogger(__name__)

# service → (max_requests, window_seconds); conservative fractions of quota
_DEFAULT_LIMITS: dict[str, tuple[int, float]] = {
    "meta": (10, 1.0),
    "tiktok": (30, 60.0),
    "shopify": (1, 1.0),
    "default": (10, 1.0),
}


class RateLimiter:
    """Sliding-window rate limiter, one window per service."""

    def __init__(self, limits: dict[str, tuple[int, float]] | None = None):
        self._limits = dict(limits or _DEFAULT_LIMITS)
        self._windows: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _limit_for(self, service: str) -> tuple[int, float]:
        return self._limits.get(service, self._limits["default"])

    def acquire(self, service: str, timeout: float = 30.0) -> bool:
        """Block until a request slot is available (or timeout).

        Returns True when a slot was acquired, False on timeout — the caller
        can then decide to skip or fail the request.  Never raises.
        """
        max_req, window = self._limit_for(service)
        deadline = time.time() + timeout

        while True:
            with self._lock:
                q = self._windows.setdefault(service, deque())
                now = time.time()
                while q and q[0] <= now - window:
                    q.popleft()
                if len(q) < max_req:
                    q.append(now)
                    return True
                wait = q[0] + window - now
            if time.time() + wait > deadline:
                _log.warning("rate_limit_timeout service=%s", service)
                return False
            time.sleep(min(wait, 0.25))

    def would_block(self, service: str) -> bool:
        """True if an acquire() right now would have to wait."""
        max_req, window = self._limit_for(service)
        with self._lock:
            q = self._windows.get(service, deque())
            now = time.time()
            live = sum(1 for t in q if t > now - window)
            return live >= max_req

    def status(self) -> dict[str, dict]:
        """Current window occupancy per service (for the dashboard)."""
        out = {}
        with self._lock:
            now = time.time()
            for service, (max_req, window) in self._limits.items():
                q = self._windows.get(service, deque())
                live = sum(1 for t in q if t > now - window)
                out[service] = {"in_window": live, "max": max_req,
                                "window_s": window}
        return out


# Module-level singleton shared by every integration
rate_limiter = RateLimiter()

__all__ = ["RateLimiter", "rate_limiter"]
