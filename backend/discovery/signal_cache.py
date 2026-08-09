"""backend.discovery.signal_cache — caching layer for expensive signal queries.

Signals (Google Trends, Meta Ad Library, Amazon bestsellers, Reddit) are the
most expensive part of discovery.  Caching them for a few hours cuts ~90% of
discovery API calls: trends simply don't move minute-to-minute.

TTL is set via SIGNAL_CACHE_TTL_H (hours, default 6).  A TTL of 0 disables
caching entirely — every call fetches fresh — which is what the test suite
uses so monkeypatched signal sources are always exercised.

On a fresh-fetch failure the cache degrades gracefully: a stale snapshot is
better than an empty discovery cycle.

Usage:
    from backend.discovery.signal_cache import get_signals_cached
    signals = get_signals_cached()          # cached ≤6h, else fresh
    signals = get_signals_cached(force_refresh=True)
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

from backend.core.persistence import load_json, save_json_atomic, state_path

_log = logging.getLogger(__name__)

_CACHE_PATH = state_path("signal_cache.json")


def _ttl_hours() -> float:
    """Cache TTL in hours; 0 (or negative) disables caching."""
    try:
        return float(os.getenv("SIGNAL_CACHE_TTL_H", "6"))
    except ValueError:
        return 6.0


def get_signals_cached(
    max_age_hours: float | None = None,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    """Return signals, from cache when fresh enough, else from the engine.

    Args:
      max_age_hours: cache TTL override; None reads SIGNAL_CACHE_TTL_H (default 6)
      force_refresh: bypass the cache and fetch fresh

    Never raises; a total failure returns whatever stale cache exists (or []).
    """
    ttl = _ttl_hours() if max_age_hours is None else max_age_hours
    caching_on = ttl > 0

    cached = load_json(_CACHE_PATH, default=None) if caching_on else None
    if not force_refresh and caching_on and isinstance(cached, dict):
        age_h = (time.time() - float(cached.get("ts", 0))) / 3600
        if age_h < ttl and isinstance(cached.get("signals"), list):
            _log.debug("signal_cache_hit age_h=%.2f signals=%d",
                       age_h, len(cached["signals"]))
            return cached["signals"]

    try:
        from core.signals import signal_engine
        signals = signal_engine.get()
        if caching_on:
            save_json_atomic(_CACHE_PATH, {"signals": signals, "ts": time.time()})
            _log.debug("signal_cache_refreshed signals=%d", len(signals))
        return signals
    except Exception as exc:
        # TTL 0 == cache fully disabled: no stale fallback, mirror a raw fetch.
        if isinstance(cached, dict) and isinstance(cached.get("signals"), list):
            _log.warning("signal_fetch_failed error=%s — serving stale cache", exc)
            return cached["signals"]
        _log.debug("signal_fetch_failed error=%s (no cache to fall back on)", exc)
        return []


def cache_status() -> dict[str, Any]:
    """Inspect the cache: freshness, size, TTL currently in force."""
    cached = load_json(_CACHE_PATH, default=None)
    ttl = _ttl_hours()
    if not isinstance(cached, dict):
        return {"status": "empty", "signals_cached": 0, "age_hours": None,
                "ttl_hours": ttl}
    age_h = (time.time() - float(cached.get("ts", 0))) / 3600
    return {
        "status": "valid" if (ttl > 0 and age_h < ttl) else "stale",
        "signals_cached": len(cached.get("signals", [])),
        "age_hours": round(age_h, 2),
        "ttl_hours": ttl,
    }


def clear_cache() -> None:
    """Drop the cached snapshot (manual refresh / tests)."""
    try:
        os.unlink(_CACHE_PATH)
        _log.info("signal_cache_cleared")
    except FileNotFoundError:
        pass
    except Exception as exc:
        _log.debug("signal_cache_clear_failed error=%s", exc)


__all__ = ["get_signals_cached", "cache_status", "clear_cache"]
