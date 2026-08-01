"""core.content.optimizer — select the best hooks and angles from analytics."""
from __future__ import annotations

from typing import Any


def best_hooks(analysis: dict[str, Any], top_n: int = 3) -> list[tuple[str, float]]:
    """Return the *top_n* best-performing hooks sorted by avg engagement.

    Parameters
    ----------
    analysis:
        Output of :func:`~core.content.analytics.analyze`.
    top_n:
        Number of top hooks to return.

    Returns
    -------
    list[tuple[str, float]]
        ``[(hook, avg_engagement), ...]`` sorted descending.
    """
    hooks = analysis.get("hooks", {})
    return sorted(hooks.items(), key=lambda x: x[1], reverse=True)[:top_n]


def best_angles(analysis: dict[str, Any], top_n: int = 3) -> list[tuple[str, float]]:
    """Return the *top_n* best-performing angles sorted by avg engagement.

    Parameters
    ----------
    analysis:
        Output of :func:`~core.content.analytics.analyze`.
    top_n:
        Number of top angles to return.

    Returns
    -------
    list[tuple[str, float]]
        ``[(angle, avg_engagement), ...]`` sorted descending.
    """
    angles = analysis.get("angles", {})
    return sorted(angles.items(), key=lambda x: x[1], reverse=True)[:top_n]
