"""services.digital_products.funnel — build_funnel_plan."""
from __future__ import annotations

from .schemas import DigitalOffer, FunnelPlan

_LEAD_MAGNET_BY_TYPE = {
    "template": "free mini-template (one section of the full offer)",
    "playbook": "free checklist covering step 1 of the playbook",
    "course": "free lesson 1 / preview module",
    "cohort": "free live workshop / masterclass",
    "ebook": "free chapter excerpt",
    "paid_report": "free summary report (headline findings only)",
    "prompt_pack": "free 3-prompt sample pack",
    "calculator": "free simplified version of the calculator",
    "dashboard_access": "free read-only demo dashboard",
    "mentorship": "free discovery/strategy call",
}

_SALES_PAGE_STRUCTURE = [
    "headline: the transformation, not the format",
    "problem agitation (what happens if this isn't solved)",
    "solution overview + what's included",
    "social proof / case studies",
    "pricing + guarantee",
    "FAQ (objection handling)",
    "single clear CTA",
]


def build_funnel_plan(offer: DigitalOffer) -> FunnelPlan:
    """Never raises."""
    lead_magnet = _LEAD_MAGNET_BY_TYPE.get(offer.product_type, "free preview/sample of the offer")
    funnel_steps = [
        f"lead magnet: {lead_magnet}",
        "email/nurture sequence (3-5 emails building toward the offer)",
        "sales page / webinar pitch",
        "checkout",
        "onboarding / delivery",
        "post-purchase follow-up (testimonial/referral ask)",
    ]
    return FunnelPlan(lead_magnet=lead_magnet, funnel_steps=funnel_steps, sales_page_structure=list(_SALES_PAGE_STRUCTURE))
