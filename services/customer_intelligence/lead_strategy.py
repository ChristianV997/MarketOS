"""services.customer_intelligence.lead_strategy — build_lead_strategy."""
from __future__ import annotations

from .schemas import LeadStrategyResult

_DEFAULT_QUALIFICATION_QUESTIONS = [
    "What's driving you to look at this now?",
    "What's your timeline?",
    "What's your budget range?",
    "Have you looked at alternatives? What did you like/dislike?",
    "Who else is involved in this decision?",
]


def build_lead_strategy(
    business_type: str, *, has_existing_audience: bool = False, budget_tier: str = "low",
) -> LeadStrategyResult:
    """Never raises."""
    lead_sources = ["organic content (owned channels)", "referral program"]
    outreach_channels = ["email", "organic social"]

    if has_existing_audience:
        lead_sources.insert(0, "existing customer/audience reactivation")
    if budget_tier in ("medium", "high"):
        lead_sources.append("paid social (Meta/TikTok)")
        outreach_channels.append("paid social ads")
    if budget_tier == "high":
        lead_sources.append("paid search")
        outreach_channels.append("SDR outbound (phone/WhatsApp)")

    return LeadStrategyResult(
        business_type=business_type, lead_sources=lead_sources,
        outreach_channels=outreach_channels,
        qualification_questions=list(_DEFAULT_QUALIFICATION_QUESTIONS),
    )
