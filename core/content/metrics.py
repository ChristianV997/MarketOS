"""core.content.metrics — evaluate organic post performance."""
from __future__ import annotations

from typing import Any


def evaluate(post: dict[str, Any]) -> dict[str, Any]:
    """Extract performance metrics from a post result dict.

    Parameters
    ----------
    post:
        Post dict containing optional ``views``, ``likes``, and
        ``engagement`` keys.

    Returns
    -------
    dict
        Standardised metrics dict with ``views``, ``likes``, and
        ``engagement``.
    """
    return {
        "views": int(post.get("views", 0)),
        "likes": int(post.get("likes", 0)),
        "engagement": float(post.get("engagement", 0.0)),
    }
