"""Single-process, in-memory rate limits for the Phase 1 MVP API."""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimitPolicy:
    name: str
    max_requests: int
    window_seconds: int
    scope: str = "ip"


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    policy: str
    limit: int
    remaining: int
    retry_after_seconds: int


_lock = threading.Lock()
_buckets: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def _positive_env(name: str, default: int, maximum: int) -> int:
    try:
        return min(max(1, int(os.getenv(name, str(default)))), maximum)
    except ValueError:
        return default


def public_run_policy() -> RateLimitPolicy:
    return RateLimitPolicy("public_commerce_run", _positive_env("MARKETOS_PUBLIC_RUN_RATE_LIMIT", 10, 1000), _positive_env("MARKETOS_PUBLIC_RUN_RATE_WINDOW_SECONDS", 600, 86400))


def event_read_policy() -> RateLimitPolicy:
    return RateLimitPolicy("event_read_api", _positive_env("MARKETOS_EVENT_READ_RATE_LIMIT", 300, 5000), _positive_env("MARKETOS_EVENT_READ_RATE_WINDOW_SECONDS", 600, 86400))


def check_rate_limit(policy: RateLimitPolicy, key: str, *, now: float | None = None) -> RateLimitResult:
    current = time.monotonic() if now is None else now
    bucket_key = (policy.name, key[:128])
    with _lock:
        bucket = _buckets[bucket_key]
        cutoff = current - policy.window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= policy.max_requests:
            retry = max(1, int(bucket[0] + policy.window_seconds - current))
            return RateLimitResult(False, policy.name, policy.max_requests, 0, retry)
        bucket.append(current)
        return RateLimitResult(True, policy.name, policy.max_requests, policy.max_requests - len(bucket), 0)


def reset_rate_limits_for_tests() -> None:
    with _lock:
        _buckets.clear()


def explain_rate_limit_status() -> dict[str, object]:
    public = public_run_policy()
    events = event_read_policy()
    return {
        "enabled": True,
        "in_memory": True,
        "distributed": False,
        "public_run_rate_limit": public.max_requests,
        "public_run_rate_window_seconds": public.window_seconds,
        "event_read_rate_limit": events.max_requests,
        "event_read_rate_window_seconds": events.window_seconds,
        "scope": "client_ip",
    }


__all__ = ["RateLimitPolicy", "RateLimitResult", "check_rate_limit", "event_read_policy", "explain_rate_limit_status", "public_run_policy", "reset_rate_limits_for_tests"]
