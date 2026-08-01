"""services.customer_intelligence.publicity_plan — build_publicity_strategy.

Reuses services.creative_growth.generate_ad_angles for the ad-angle
portion rather than duplicating angle logic.
"""
from __future__ import annotations

from .schemas import ICPResult, PublicityStrategyResult

_DEFAULT_PR_ANGLES = [
    "founder story / why this business exists",
    "before-and-after customer transformation",
    "behind-the-scenes / how it's made",
    "local community involvement (for location-based businesses)",
]
_DEFAULT_CONTENT_PILLARS = ["education", "social proof", "behind-the-scenes", "offer/promotion"]


def build_publicity_strategy(business_type: str, *, icp: ICPResult | None = None) -> PublicityStrategyResult:
    """Never raises."""
    ad_angles: list[str] = []
    try:
        from services.creative_growth import generate_ad_angles
        ad_angles = generate_ad_angles(business_type)
    except Exception:
        ad_angles = ["problem-solution", "transformation", "convenience"]

    channels = ["organic social", "email"]
    if icp and icp.buyer_profile.get("price_sensitivity") == "low":
        channels.append("PR / press outreach")
    channels.append("paid social")

    return PublicityStrategyResult(
        business_type=business_type, ad_angles=ad_angles,
        pr_angles=list(_DEFAULT_PR_ANGLES), content_pillars=list(_DEFAULT_CONTENT_PILLARS),
        channels=channels,
    )
