"""core.simulation.evaluator — pre-execution performance estimator."""
from __future__ import annotations

from typing import Any


def evaluate(
    product: str,
    persona: dict[str, Any],
    landing: dict[str, Any],
    signal: dict[str, Any],
) -> dict[str, Any]:
    """Estimate ad performance before spending money.

    Uses the signal engagement rate as a base and scales to CTR / CVR / ROAS
    estimates.

    Parameters
    ----------
    product:
        Product label.
    persona:
        Audience persona dict.
    landing:
        Landing page spec dict.
    signal:
        Normalised signal dict containing an ``"engagement"`` key (or computable
        from ``likes``, ``comments``, ``views``).

    Returns
    -------
    dict
        ``predicted_ctr``, ``predicted_cvr``, ``predicted_roas``.
    """
    engagement = float(signal.get("engagement", 0.0))
    if engagement == 0.0:
        views = int(signal.get("views", 0))
        likes = int(signal.get("likes", 0))
        comments = int(signal.get("comments", 0))
        if views > 0:
            engagement = (likes + comments) / views

    return {
        "predicted_ctr": engagement,
        "predicted_cvr": engagement * 0.5,
        "predicted_roas": engagement * 2.0,
    }
