"""core.content.features — feature extraction from content performance entries."""
from __future__ import annotations

from typing import Any


def extract(post: dict[str, Any]) -> dict[str, Any]:
    """Extract a feature dict from a post performance entry.

    Parameters
    ----------
    post:
        Post dict with at least ``hook``, ``angle``, ``views``, and
        ``engagement`` keys.

    Returns
    -------
    dict
        Feature dict suitable for hook/angle analytics.
    """
    return {
        "hook": post.get("hook", ""),
        "angle": post.get("angle", ""),
        "format": post.get("format", "demo"),
        "views": int(post.get("views", 0)),
        "engagement": float(post.get("engagement", 0.0)),
    }
