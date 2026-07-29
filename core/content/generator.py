"""core.content.generator — organic content generation for TikTok-first strategy."""
from __future__ import annotations

from typing import Any


def generate_content(product: str, angle: str) -> dict[str, Any]:
    """Return an organic content spec for *product* and *angle*.

    Parameters
    ----------
    product:
        Product to feature.
    angle:
        Content angle (e.g. ``"satisfaction"``).

    Returns
    -------
    dict
        Content spec with ``hook``, ``script``, and ``cta`` keys.
    """
    return {
        "hook": f"{angle} hook",
        "script": f"show {product} solving problem visually",
        "cta": "follow for more",
        "product": product,
        "angle": angle,
    }
