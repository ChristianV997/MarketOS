"""core.landing.generator — generate landing page structure from product + angle."""
from __future__ import annotations

from typing import Any

_DEFAULT_SECTIONS = ["problem", "solution", "benefits", "social proof", "cta"]


def generate_landing(product: str, angle: str) -> dict[str, Any]:
    """Return a landing page spec for *product* oriented around *angle*.

    Parameters
    ----------
    product:
        Product name or label string.
    angle:
        Primary content angle (e.g. ``"satisfaction"``).

    Returns
    -------
    dict
        Dict with ``headline`` and ``sections`` keys.
    """
    return {
        "headline": f"This {product} solves your problem instantly",
        "angle": angle,
        "sections": list(_DEFAULT_SECTIONS),
    }
