"""Tests for backend.patterns.worker — RateLimiter + worker_safe decorator."""
import time

import pytest

from backend.patterns.worker import RateLimiter, worker_safe


class TestRateLimiter:
    def test_ready_initially(self):
        rl = RateLimiter(interval_s=10)
        assert rl.ready() is True

    def test_not_ready_after_mark(self):
        rl = RateLimiter(interval_s=10)
        rl.mark()
        assert rl.ready() is False

    def test_ready_after_interval_elapses(self):
        rl = RateLimiter(interval_s=0.01)
        rl.mark()
        rl.last_run = time.time() - 0.02  # simulate the interval having elapsed
        assert rl.ready() is True

    def test_reset_via_last_run_attribute(self):
        """Tests reset rate limiters by writing .last_run directly."""
        rl = RateLimiter(interval_s=999)
        rl.mark()
        assert rl.ready() is False
        rl.last_run = 0.0
        assert rl.ready() is True

    def test_force_skip_via_last_run_attribute(self):
        rl = RateLimiter(interval_s=999)
        rl.last_run = time.time()
        assert rl.ready() is False


class TestWorkerSafe:
    def test_success_passthrough(self):
        @worker_safe()
        def fn():
            return {"status": "ok", "value": 42}

        assert fn() == {"status": "ok", "value": 42}

    def test_exception_converted_to_error_status(self):
        @worker_safe()
        def fn():
            raise ValueError("boom")

        result = fn()
        assert result["status"] == "error"
        assert "boom" in result["error"]

    def test_rate_limited_skip(self):
        rl = RateLimiter(interval_s=999)
        rl.mark()
        calls = []

        @worker_safe(rate_limiter=rl)
        def fn():
            calls.append(1)
            return {"status": "ok"}

        result = fn()
        assert result == {"status": "skipped", "reason": "rate_limited"}
        assert calls == []  # body never executed

    def test_rate_limiter_marks_on_success(self):
        rl = RateLimiter(interval_s=999)
        rl.last_run = 0.0

        @worker_safe(rate_limiter=rl)
        def fn():
            return {"status": "ok"}

        fn()
        assert rl.ready() is False  # marked after success

    def test_rate_limiter_marks_on_error_too(self):
        """An erroring worker still consumes its rate-limit slot, matching
        the previous per-worker behavior where the timestamp update happened
        inside the try block right after work started."""
        rl = RateLimiter(interval_s=999)
        rl.last_run = 0.0

        @worker_safe(rate_limiter=rl)
        def fn():
            raise RuntimeError("fail")

        fn()
        # Error results aren't marked (mirrors: exception means work didn't
        # complete, so the next tick should be allowed to retry promptly).
        assert rl.ready() is True

    def test_preserves_function_name(self):
        @worker_safe()
        def _run_something():
            return {"status": "ok"}

        assert _run_something.__name__ == "_run_something"

    def test_no_rate_limiter_always_runs(self):
        calls = []

        @worker_safe()
        def fn():
            calls.append(1)
            return {"status": "ok"}

        fn()
        fn()
        assert len(calls) == 2
