"""Tests for retry middleware and the sliding-window rate limiter."""
import time

import pytest

from backend.integrations.rate_limiter import RateLimiter
from backend.integrations.retry_middleware import retry_call


# ── retry_call ────────────────────────────────────────────────────────────────

def test_success_first_try():
    assert retry_call(lambda: 42) == 42


def test_retries_transient_then_succeeds():
    calls = {"n": 0}

    def _flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("blip")
        return "ok"

    assert retry_call(_flaky, attempts=3, base_delay=0.01) == "ok"
    assert calls["n"] == 3


def test_exhausted_attempts_raise():
    calls = {"n": 0}

    def _always_fails():
        calls["n"] += 1
        raise TimeoutError("down")

    with pytest.raises(TimeoutError):
        retry_call(_always_fails, attempts=3, base_delay=0.01)
    assert calls["n"] == 3


def test_non_retryable_fails_fast():
    calls = {"n": 0}

    def _bad_request():
        calls["n"] += 1
        raise ValueError("400 bad request")   # not transient

    with pytest.raises(ValueError):
        retry_call(_bad_request, attempts=5, base_delay=0.01)
    assert calls["n"] == 1                     # no retries burned


def test_retryable_http_status():
    """Exceptions carrying a response with a 5xx/429 status are retried."""
    class _Resp:
        status_code = 503

    class _HTTPError(Exception):
        response = _Resp()

    calls = {"n": 0}

    def _flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise _HTTPError("503")
        return "recovered"

    assert retry_call(_flaky, attempts=3, base_delay=0.01) == "recovered"


def test_non_retryable_http_status_fails_fast():
    class _Resp:
        status_code = 401

    class _HTTPError(Exception):
        response = _Resp()

    calls = {"n": 0}

    def _unauthorized():
        calls["n"] += 1
        raise _HTTPError("401")

    with pytest.raises(_HTTPError):
        retry_call(_unauthorized, attempts=5, base_delay=0.01)
    assert calls["n"] == 1


# ── rate limiter ──────────────────────────────────────────────────────────────

def test_acquire_within_limit_is_instant():
    rl = RateLimiter({"svc": (5, 1.0), "default": (5, 1.0)})
    start = time.time()
    for _ in range(5):
        assert rl.acquire("svc") is True
    assert time.time() - start < 0.1


def test_acquire_blocks_then_frees():
    rl = RateLimiter({"svc": (2, 0.2), "default": (2, 0.2)})
    rl.acquire("svc")
    rl.acquire("svc")
    assert rl.would_block("svc") is True

    start = time.time()
    assert rl.acquire("svc", timeout=2.0) is True   # waits for window to slide
    assert 0.05 < time.time() - start < 1.0


def test_acquire_timeout_returns_false():
    rl = RateLimiter({"svc": (1, 10.0), "default": (1, 10.0)})
    rl.acquire("svc")
    assert rl.acquire("svc", timeout=0.05) is False


def test_unknown_service_uses_default():
    rl = RateLimiter({"default": (1, 10.0)})
    assert rl.acquire("never_seen") is True
    assert rl.would_block("never_seen") is True


def test_status_shape():
    rl = RateLimiter({"svc": (3, 1.0), "default": (3, 1.0)})
    rl.acquire("svc")
    status = rl.status()
    assert status["svc"]["in_window"] == 1
    assert status["svc"]["max"] == 3
