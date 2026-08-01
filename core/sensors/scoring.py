"""core.sensors.scoring — engagement-based scoring for normalised signals."""
from __future__ import annotations

from typing import Any

ENGAGEMENT_WEIGHT: float = 0.6
VIEWS_WEIGHT: float = 1e-6


def engagement_rate(signal: dict[str, Any]) -> float:
    """Compute (likes + comments) / views, or 0 when views is zero."""
    views = int(signal.get("views", 0))
    if views == 0:
        return 0.0
    likes = int(signal.get("likes", 0))
    comments = int(signal.get("comments", 0))
    return (likes + comments) / views


def score(signal: dict[str, Any]) -> float:
    """Compute a composite score for a normalised signal.

    Formula: ``engagement_rate * 0.6 + views * 1e-6``

    Parameters
    ----------
    signal:
        Normalised signal dict containing ``views``, ``likes``, ``comments``.

    Returns
    -------
    float
        Composite score (higher is better).
    """
    views = int(signal.get("views", 0))
    return engagement_rate(signal) * ENGAGEMENT_WEIGHT + views * VIEWS_WEIGHT
