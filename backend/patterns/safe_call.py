"""backend.patterns.safe_call — catch-log-default decorator for integration clients.

meta_ads_client.py and tiktok_ads.py each wrap every public function
(create_campaign, create_ad_set, create_ad, pause_campaign, scale_budget,
fetch_roas, ...) in the same boilerplate:

    def create_campaign(...) -> str:
        try:
            ...
            return cid
        except Exception:
            _log.exception("create_campaign failed")
            return ""

That's 11+ near-identical try/except blocks across the two clients. This
decorator extracts the pattern so each function only implements its happy
path; the fallback value and logging are declared once, at the decoration
site, instead of re-typed per function.
"""
from __future__ import annotations

import functools
import logging
from typing import Any, Callable, TypeVar

T = TypeVar("T")


def safe_call(default: T | Callable[[], T] = None, logger: logging.Logger | None = None) -> Callable:
    """Decorator: run ``fn``; on any exception, log it and return ``default``.

    ``default`` may be a plain value (str, bool, ...) or a zero-arg callable
    — use a callable for mutable defaults (dict, list) so each failure gets
    a fresh instance rather than a shared one.

    Usage:
        @safe_call(default="")
        def create_campaign(name: str) -> str:
            resp = _graph_post(...)
            return str(resp["id"])

        @safe_call(default=dict)   # factory: fresh {} per failure
        def fetch_roas(ids: list[str]) -> dict[str, float]:
            ...
    """
    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        log = logger or logging.getLogger(fn.__module__)

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            try:
                return fn(*args, **kwargs)
            except Exception:
                log.exception(f"{fn.__name__} failed")
                return default() if callable(default) else default
        return wrapper
    return decorator


__all__ = ["safe_call"]
