"""ads — format hooks into structured ad objects."""
from __future__ import annotations

_PRIMARY_TEXT_TEMPLATES = {
    "tiktok":         "Trending now: {raw_text}. Join thousands discovering this.",
    "meta":           "Trending now: {raw_text}. Join thousands discovering this.",
    "youtube":        "Trending now: {raw_text}. Join thousands discovering this.",
    "amazon":         "Top-rated and bestselling. {raw_text}. Limited stock available.",
    "google":         "People are searching for this right now. {raw_text}.",
    "google_trends":  "People are searching for this right now. {raw_text}.",
    "linkedin":       "Professionals are talking about this. {raw_text}.",
}
_DEFAULT_PRIMARY_TEXT = "{raw_text}. See why this is trending."

_CTAS = {
    "finance":      "Start Saving Today",
    "productivity": "Try It Free",
    "ecommerce":    "Shop Now",
    "marketing":    "Grow Your Business",
    "review":       "See Reviews",
    "lifestyle":    "Discover More",
    "beauty":       "Shop the Look",
    "business":     "Scale Now",
}

_DEFAULT_CTA = "Learn More"


_READY_THRESHOLD = 0.50


def format_ads(hooks: list[dict]) -> list[dict]:
    ads = []
    for rank, h in enumerate(hooks):
        category = h["category"]
        cta = _CTAS.get(category, _DEFAULT_CTA)
        headline = h["hook"][:80]
        tmpl = _PRIMARY_TEXT_TEMPLATES.get(h["source"], _DEFAULT_PRIMARY_TEXT)
        primary_text = tmpl.format(raw_text=h["raw_text"])[:200]
        engagement = h["engagement"]
        # rank_score: blend of engagement (quality) and position (0-indexed, earlier = higher)
        rank_score = round(engagement * 0.8 + max(0.0, 1.0 - rank / max(len(hooks), 1)) * 0.2, 4)
        ads.append({
            "headline":       headline,
            "primary_text":   primary_text,
            "call_to_action": cta,
            "category":       category,
            "source":         h["source"],
            "source_url":     h["url"],
            "external_id":    h["external_id"],
            "engagement":     engagement,
            "rank_score":     rank_score,
            "hook_variant":   h.get("hook_variant", 1),
            "ready_for_ads":  engagement >= _READY_THRESHOLD and bool(headline),
        })
    return ads
