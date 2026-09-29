"""services.market_research_evidence.freshness — as-of freshness
classification for one observed_at timestamp.

Deterministic date arithmetic only; no clock reads beyond what the caller
passes in as `as_of`.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .schemas import DEFAULT_FRESHNESS_DAYS


def _parse_day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except (TypeError, ValueError):
        return None


def classify_freshness(observed_at: Any, as_of: Any, *, freshness_days: int = DEFAULT_FRESHNESS_DAYS) -> str:
    """Returns one of 'supplied', 'stale', 'future', 'unknown', 'missing'.

    'missing' is for the caller (no observed_at supplied at all) to signal
    explicitly; this function returns 'unknown' whenever an observed_at
    value was supplied but could not be parsed as a real calendar date, and
    'supplied' whenever no as_of reference is available to compare against
    (freshness is then simply unevaluated, not silently assumed fresh).
    """
    if observed_at in (None, ""):
        return "missing"
    observed_day = _parse_day(observed_at)
    if observed_day is None:
        return "unknown"
    as_of_day = _parse_day(as_of) if as_of not in (None, "") else None
    if as_of_day is None:
        return "supplied"
    if observed_day > as_of_day:
        return "future"
    if (as_of_day - observed_day) > timedelta(days=freshness_days):
        return "stale"
    return "supplied"


__all__ = ["classify_freshness"]
