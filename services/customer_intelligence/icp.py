"""services.customer_intelligence.icp — generate_icp, generate_customer_segments.

Where a category has real, offline-ingested public-dataset priors
(backend.data.category_priors, sourced from Amazon Reviews 2023 + Olist —
free, already in this repo, no live scrape/cost), those inform the ICP's
repeat-purchase framing; otherwise this degrades to documented generic
heuristics rather than fabricating a number.
"""
from __future__ import annotations

from typing import Any

from .schemas import CustomerSegmentsResult, ICPResult

_GENERIC_PAIN_POINTS = [
    "not enough qualified leads", "too much time spent on unqualified inquiries",
    "inconsistent close rate", "price objections without a clear differentiator",
]
_GENERIC_TRIGGERS = ["recent life event", "seasonal urgency", "competitor dissatisfaction", "referral"]


def generate_icp(
    business_type: str, *, target_geo: str = "MX", category: str = "general",
    price_point: float | None = None,
) -> ICPResult:
    """Never raises."""
    data_sources = ["heuristic (no live/public data source configured)"]
    repeat_rate = None
    try:
        from backend.data.category_priors import category_prior
        repeat_rate = category_prior(category, "repeat_rate", None)
        if repeat_rate is not None:
            data_sources = ["backend.data.category_priors (Amazon Reviews 2023 / Olist, offline-ingested)"]
    except Exception:
        pass

    buyer_profile: dict[str, Any] = {
        "business_type": business_type,
        "geo": target_geo,
        "price_sensitivity": "high" if (price_point or 0) < 500 else "moderate" if (price_point or 0) < 5000 else "low",
        "repeat_purchase_likelihood": repeat_rate if repeat_rate is not None else "unknown (no ingested priors for this category)",
    }

    return ICPResult(
        business_type=business_type, target_geo=target_geo,
        buyer_profile=buyer_profile, pain_points=list(_GENERIC_PAIN_POINTS),
        triggers=list(_GENERIC_TRIGGERS), data_sources=data_sources,
    )


def generate_customer_segments(business_type: str, *, icp: ICPResult | None = None) -> CustomerSegmentsResult:
    """Never raises. A simple 3-tier segmentation (price-anchored) —
    genuinely useful as a starting structure, refine with real CRM/order
    data once available."""
    segments = [
        {"name": "price-driven", "description": "compares on price first, needs a clear value anchor",
         "estimated_share_pct": 50.0, "priority": "secondary"},
        {"name": "value-driven", "description": "will pay more for trust/quality signals", "estimated_share_pct": 35.0, "priority": "primary"},
        {"name": "urgency-driven", "description": "has an acute trigger (event/deadline), least price-sensitive",
         "estimated_share_pct": 15.0, "priority": "primary"},
    ]
    return CustomerSegmentsResult(business_type=business_type, segments=segments)
