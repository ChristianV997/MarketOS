"""services.digital_products.content_plan — generate_content_plan.

Reuses services.creative_growth.generate_ad_angles rather than a second
angle-generation implementation.
"""
from __future__ import annotations

from typing import Any

from .schemas import DigitalOffer


def generate_content_plan(offer: DigitalOffer) -> dict[str, Any]:
    """Never raises."""
    angles: list[str] = []
    try:
        from services.creative_growth import generate_ad_angles
        angles = generate_ad_angles(offer.offer_name)
    except Exception:
        angles = ["problem-solution", "transformation", "curiosity"]

    content_pillars = [
        f"the problem {offer.target_customer or 'your audience'} has before this offer",
        "proof/case-study content",
        "behind-the-scenes of building the offer",
        "direct promotion / launch content",
    ]

    return {"angles": angles, "content_pillars": content_pillars}
