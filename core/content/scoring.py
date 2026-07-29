"""core.content.scoring — score organic posts for promotion eligibility."""
from __future__ import annotations

from typing import Any

# Content scoring weights (tuned for organic content where engagement is the
# primary signal, unlike sensor scoring which weights views more heavily).
ENGAGEMENT_WEIGHT: float = 0.7
VIEWS_WEIGHT: float = 1e-6


def _post_score(post: dict[str, Any]) -> float:
    """Shared scoring kernel used by both this module and hook_scoring."""
    engagement = float(post.get("engagement", 0.0))
    views = int(post.get("views", 0))
    return engagement * ENGAGEMENT_WEIGHT + views * VIEWS_WEIGHT


def score(post: dict[str, Any]) -> float:
    """Compute a composite score for an organic post.

    Formula: ``engagement * 0.7 + views * 1e-6``

    Parameters
    ----------
    post:
        Post dict with ``engagement`` and ``views`` keys.

    Returns
    -------
    float
        Composite score (higher → better promotion candidate).
    """
    return _post_score(post)
