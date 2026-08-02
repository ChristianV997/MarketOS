"""services.creative_growth.ugc_plan — generate_ugc_briefs.

Wraps core.ugc.creator_tracker.creator_tracker: when real seeding history
exists, suggests actual proven creators (top_creators by cost-per-order);
otherwise falls back to generic creator-tier guidance (micro/nano/macro),
since that's public marketing knowledge, not something requiring a paid
lookup or a live scrape.
"""
from __future__ import annotations

from typing import Any

# Generic creator-tier guidance — used until real seeding history exists.
_CREATOR_TIERS = [
    {"tier": "nano", "followers": "1k-10k", "typical_cost": "product only or <$50", "strength": "high trust, cheap, slow reach"},
    {"tier": "micro", "followers": "10k-100k", "typical_cost": "$50-300", "strength": "best cost-per-order ratio for testing"},
    {"tier": "macro", "followers": "100k+", "typical_cost": "$300+", "strength": "reach, slower to validate cost-per-order"},
]


def generate_ugc_briefs(product_name: str, angles: list[str], *, n_creators: int = 3) -> list[dict[str, Any]]:
    """Never raises. One brief per angle: talking points, content type,
    creator suggestion, and standard guardrails (no unsupported claims)."""
    creator_suggestions: list[dict[str, Any]] = []
    try:
        from core.ugc.creator_tracker import creator_tracker
        top = creator_tracker.top_creators(n=n_creators, by="avg_cost_per_order")
        creator_suggestions = [{"creator_id": cid, **stats} for cid, stats in top]
    except Exception:
        pass
    if not creator_suggestions:
        creator_suggestions = list(_CREATOR_TIERS[:n_creators])

    briefs = []
    for angle in (angles or []):
        briefs.append({
            "product": product_name,
            "angle": angle,
            "content_type": "unboxing" if angle in ("curiosity", "transformation") else "review",
            "talking_points": [
                f"Open with the {angle} angle in the first 2 seconds",
                "Show the product in real use, not a studio shot",
                "State one concrete, verifiable benefit — no unsupported claims",
                "End with a clear, single call to action",
            ],
            "creator_suggestions": creator_suggestions,
            "guardrails": [
                "no medical/health claims unless independently verified",
                "disclose gifted/paid product per platform + regional ad-disclosure rules",
                "no binding promises on behalf of the brand (pricing, availability, refunds)",
            ],
        })
    return briefs
