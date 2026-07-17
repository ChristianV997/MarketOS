"""backend.patterns.worker — rate limiting + error handling for orchestrator workers.

orchestrator/main.py has 9 worker functions that each repeat two patterns:

  1. Rate-limit gating:
       if now - _last_x_ts < _X_MIN_INTERVAL_S:
           return {"status": "skipped", "reason": "rate_limited"}

  2. Outer exception handling:
       try:
           ...
       except Exception as exc:
           _log.exception("x_failed error=%s", exc)
           return {"status": "error", "error": str(exc)}

This module extracts both into a decorator so worker bodies only contain
business logic. Internal best-effort sub-steps (e.g. "index signals in the
vector store, but don't fail the whole worker if that breaks") are
untouched — those are intentional partial-failure branches, not the
duplicated boilerplate this targets.
"""
from __future__ import annotations

import functools
import time
from typing import Any, Callable

try:
    import structlog
    _log = structlog.get_logger(__name__)
except ImportError:
    import logging
    _log = logging.getLogger(__name__)


class RateLimiter:
    """Minimal 'don't run more than every N seconds' gate.

    ``last_run`` is a plain attribute (not a property) so tests can reset it
    directly, e.g. ``limiter.last_run = 0.0`` to force the next call through,
    or ``limiter.last_run = time.time()`` to force a skip.
    """

    def __init__(self, interval_s: float):
        self.interval_s = interval_s
        self.last_run = 0.0

    def ready(self) -> bool:
        return time.time() - self.last_run >= self.interval_s

    def mark(self) -> None:
        self.last_run = time.time()


def worker_safe(rate_limiter: RateLimiter | None = None) -> Callable:
    """Decorator standardizing rate-limit skip + exception handling.

    The wrapped function should return a status dict on success, e.g.
    ``{"status": "ok", ...}``. Any exception raised is caught, logged with
    the worker's name, and converted to ``{"status": "error", "error": str(exc)}``
    — the wrapped body no longer needs its own try/except for this.

    Usage:
        _dropship_limiter = RateLimiter(interval_s=900)

        @worker_safe(rate_limiter=_dropship_limiter)
        def _run_dropship_pipeline() -> dict[str, Any]:
            summary = run_dropship_cycle()
            return {"status": "ok", "launched": summary["launched"]}
    """
    def decorator(fn: Callable[[], dict[str, Any]]) -> Callable[[], dict[str, Any]]:
        @functools.wraps(fn)
        def wrapper() -> dict[str, Any]:
            if rate_limiter is not None and not rate_limiter.ready():
                return {"status": "skipped", "reason": "rate_limited"}
            try:
                result = fn()
            except Exception as exc:
                _log.exception(f"{fn.__name__}_failed error=%s", exc)
                return {"status": "error", "error": str(exc)}
            if rate_limiter is not None and result.get("status") not in ("skipped",):
                rate_limiter.mark()
            return result
        return wrapper
    return decorator


__all__ = ["RateLimiter", "worker_safe"]
