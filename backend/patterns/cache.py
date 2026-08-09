"""backend.patterns.cache — TTL aggregation cache for repeated log reads.

campaign_performance() and calculate_profitability() re-read and
re-aggregate their entire backing JSONL log on every call, even when
called repeatedly within the same second (e.g. a dashboard polling loop).
This cache holds the last computed result per cache key for ``ttl_s``
seconds, dividing the O(n) aggregation cost by however many calls land
within the TTL window.

Freshness is enforced by invalidation, not just TTL: the writer side
(record_metric, etc.) should call ``cache.invalidate()`` after appending a
new observation, so a fresh write is visible on the very next read instead
of waiting out the TTL. TTL alone is the ceiling on staleness; invalidation
on write is what keeps correctness intact.
"""
from __future__ import annotations

import time
from typing import Any, Callable


class AggregationCache:
    """Per-key TTL cache with explicit invalidation.

    Usage:
        _perf_cache = AggregationCache(ttl_s=600)

        def campaign_performance(lookback_days=7):
            key = f"perf_{lookback_days}"
            return _perf_cache.get_or_compute(key, lambda: _compute(lookback_days))

        def record_metric(...):
            _append(...)
            _perf_cache.invalidate()   # next read recomputes, not stale
    """

    def __init__(self, ttl_s: float = 600.0):
        self.ttl_s = ttl_s
        self._cache: dict[str, Any] = {}
        self._timestamps: dict[str, float] = {}

    def get_or_compute(self, key: str, compute_fn: Callable[[], Any]) -> Any:
        """Return the cached value for ``key`` if fresh, else recompute."""
        if key in self._cache:
            age = time.time() - self._timestamps[key]
            if age < self.ttl_s:
                return self._cache[key]
        result = compute_fn()
        self._cache[key] = result
        self._timestamps[key] = time.time()
        return result

    def invalidate(self, key: str | None = None) -> None:
        """Drop one cached key, or the entire cache when ``key`` is None."""
        if key is None:
            self._cache.clear()
            self._timestamps.clear()
        else:
            self._cache.pop(key, None)
            self._timestamps.pop(key, None)

    def stats(self) -> dict:
        """Debug helper: how many keys are cached and their ages."""
        now = time.time()
        return {
            "keys": len(self._cache),
            "ages_s": {k: round(now - ts, 1) for k, ts in self._timestamps.items()},
        }


__all__ = ["AggregationCache"]
