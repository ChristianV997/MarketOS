"""Tests for backend.patterns.cache — AggregationCache."""
import time

import pytest

from backend.patterns.cache import AggregationCache


class TestAggregationCache:
    def test_computes_on_first_call(self):
        cache = AggregationCache(ttl_s=600)
        calls = []

        def compute():
            calls.append(1)
            return "result"

        assert cache.get_or_compute("k", compute) == "result"
        assert len(calls) == 1

    def test_returns_cached_within_ttl(self):
        cache = AggregationCache(ttl_s=600)
        calls = []

        def compute():
            calls.append(1)
            return len(calls)

        r1 = cache.get_or_compute("k", compute)
        r2 = cache.get_or_compute("k", compute)
        assert r1 == r2 == 1
        assert len(calls) == 1  # only computed once

    def test_recomputes_after_ttl_expires(self):
        cache = AggregationCache(ttl_s=0.01)
        calls = []

        def compute():
            calls.append(1)
            return len(calls)

        cache.get_or_compute("k", compute)
        time.sleep(0.02)
        cache.get_or_compute("k", compute)
        assert len(calls) == 2

    def test_different_keys_independent(self):
        cache = AggregationCache(ttl_s=600)
        assert cache.get_or_compute("a", lambda: "A") == "A"
        assert cache.get_or_compute("b", lambda: "B") == "B"

    def test_invalidate_single_key(self):
        cache = AggregationCache(ttl_s=600)
        calls = []

        def compute():
            calls.append(1)
            return len(calls)

        cache.get_or_compute("k", compute)
        cache.invalidate("k")
        cache.get_or_compute("k", compute)
        assert len(calls) == 2

    def test_invalidate_all_keys(self):
        cache = AggregationCache(ttl_s=600)
        cache.get_or_compute("a", lambda: "A")
        cache.get_or_compute("b", lambda: "B")
        cache.invalidate()
        assert cache.stats()["keys"] == 0

    def test_invalidate_nonexistent_key_is_noop(self):
        cache = AggregationCache(ttl_s=600)
        cache.invalidate("nonexistent")  # should not raise

    def test_stats_reports_key_count_and_ages(self):
        cache = AggregationCache(ttl_s=600)
        cache.get_or_compute("k", lambda: "v")
        stats = cache.stats()
        assert stats["keys"] == 1
        assert "k" in stats["ages_s"]
        assert stats["ages_s"]["k"] >= 0
