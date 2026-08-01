"""services.customer_intelligence.vertical_playbooks — build_vertical_playbook.

Content below is authored from established, publicly-known sales/marketing
domain practice for each vertical (not a live scrape — there is no free
public API for "buyer persona per business vertical"). Where a vertical's
economics can be grounded in this repo's own free, offline-ingested public
datasets (backend.data.category_priors — Amazon Reviews 2023 / Olist), that
takes precedence over a hand-picked number; every other field is static,
reusable structure, not fabricated "real-time" data.
"""
from __future__ import annotations

from .schemas import VerticalPlaybook

_PLAYBOOKS: dict[str, dict] = {
    "real_estate": {
        "buyer_profile": {"who": "homeowner/investor, 30-55, considering buy/sell/rent within 3-6 months",
                           "decision_style": "high-involvement, multi-stakeholder (often a partner/spouse)"},
        "pain_points": ["market uncertainty", "not knowing true property value", "financing complexity", "timeline pressure (lease ending, growing family)"],
        "high_value_triggers": ["job relocation", "growing family", "lease expiring", "life event (marriage/divorce/inheritance)"],
        "offer_angles": ["free property valuation", "off-market inventory access", "financing pre-qualification help"],
        "lead_sources": ["Zillow/portal leads", "open house sign-ins", "referral network", "geo-targeted social ads"],
        "outreach_channels": ["phone/SMS follow-up within 5 minutes of inquiry", "WhatsApp", "email drip"],
        "ad_angles": ["home value calculator", "market report for the area", "success story with specific numbers"],
        "landing_page_structure": ["value prop headline", "instant valuation tool", "recent local sales proof", "testimonial", "single CTA: book a call"],
        "qualification_questions": ["Buying, selling, or both?", "Timeline?", "Pre-approved for financing?", "Working with another agent?"],
        "appointment_setting_logic": {"speed_to_lead": "call/message within 5 minutes", "no_show_policy": "confirm 24h and 1h before"},
        "monetization_model": {"type": "commission", "typical_range": "2-3% of transaction value"},
        "risks": ["long sales cycle (weeks to months)", "regulatory/licensing constraints on claims", "high lead cost in competitive metros"],
    },
    "car_sales": {
        "buyer_profile": {"who": "individual or small-business buyer, comparison-shopping across 2-4 dealers/listings",
                           "decision_style": "price + trust + financing terms"},
        "pain_points": ["distrust of sales pressure", "financing/APR confusion", "trade-in valuation opacity"],
        "high_value_triggers": ["lease ending", "vehicle breakdown", "family size change", "new job with commute"],
        "offer_angles": ["transparent pricing / no-haggle", "instant trade-in estimate", "financing pre-approval in minutes"],
        "lead_sources": ["marketplace listings (AutoTrader-style)", "geo-targeted social ads", "referral", "walk-in"],
        "outreach_channels": ["SMS", "phone", "WhatsApp", "email"],
        "ad_angles": ["price transparency", "trade-in value calculator", "financing calculator"],
        "landing_page_structure": ["specific vehicle/offer headline", "price + financing estimate", "trade-in tool", "reviews", "single CTA: schedule test drive"],
        "qualification_questions": ["New or used?", "Budget/monthly payment target?", "Trade-in vehicle?", "Timeline to purchase?"],
        "appointment_setting_logic": {"speed_to_lead": "respond within 10 minutes", "no_show_policy": "confirm same-day"},
        "monetization_model": {"type": "unit margin + financing/backend commission", "typical_range": "varies widely by vehicle class"},
        "risks": ["thin margins on high-competition listings", "financing/advertising regulatory compliance (APR disclosure)"],
    },
    "ecommerce_brand": {
        "buyer_profile": {"who": "impulse-to-considered online shopper, discovers via social/search",
                           "decision_style": "price + social proof + shipping/return confidence"},
        "pain_points": ["decision paralysis across many similar products", "shipping/return anxiety", "trust in an unfamiliar brand"],
        "high_value_triggers": ["seasonal/gift occasion", "problem just became acute (broke/wore out)", "influencer/UGC exposure"],
        "offer_angles": ["bundle discount", "first-order discount", "free/fast shipping", "money-back guarantee"],
        "lead_sources": ["paid social", "organic UGC/creator seeding", "search", "email list"],
        "outreach_channels": ["email/SMS abandoned-cart flow", "retargeting ads"],
        "ad_angles": ["problem-solution", "transformation", "social proof / UGC", "curiosity"],
        "landing_page_structure": ["hero benefit + product shot", "social proof (reviews/UGC)", "how it works", "guarantee/returns policy", "single clear CTA"],
        "qualification_questions": ["n/a — this is direct-purchase, not appointment-based"],
        "appointment_setting_logic": {"note": "not applicable to this vertical; see services.ecommerce_operator instead"},
        "monetization_model": {"type": "unit margin per order", "typical_range": "see services.unit_economics for exact math"},
        "risks": ["platform attribution inflation (see backend.metrics.attribution)", "creative fatigue", "supplier/fulfillment risk"],
    },
    "clinic_wellness": {
        "buyer_profile": {"who": "patient/client seeking a specific outcome (pain relief, aesthetics, mental health, fitness)",
                           "decision_style": "trust + credentials + outcome evidence, high sensitivity to claims"},
        "pain_points": ["unresolved symptom/condition", "distrust from past bad experiences", "cost/insurance confusion"],
        "high_value_triggers": ["new/worsening symptom", "insurance renewal window", "referral from another provider", "life event (injury, new year)"],
        "offer_angles": ["free/low-cost initial consultation", "outcome-based case study (with consent)", "insurance/financing clarity"],
        "lead_sources": ["local search/maps", "referral from other providers", "geo-targeted social ads", "existing patient reactivation"],
        "outreach_channels": ["phone", "SMS reminders", "patient portal/email"],
        "ad_angles": ["symptom-specific problem-solution", "credential/trust signal", "testimonial (compliant with health-claim rules)"],
        "landing_page_structure": ["outcome headline (compliant)", "credentials/certifications", "testimonials", "insurance/pricing clarity", "single CTA: book consultation"],
        "qualification_questions": ["What symptom/goal brings you in?", "How long has this been an issue?", "Insurance or self-pay?", "Any prior treatment for this?"],
        "appointment_setting_logic": {"speed_to_lead": "same-day callback", "no_show_policy": "confirm 48h and 2h before; waitlist for cancellations"},
        "monetization_model": {"type": "per-visit fee or package/membership", "typical_range": "highly vertical-specific"},
        "risks": ["health-claim regulatory exposure — never overstate outcomes", "HIPAA/privacy-equivalent data handling", "no-show rate erodes calendar economics"],
    },
    "home_services": {
        "buyer_profile": {"who": "homeowner with an urgent or planned repair/improvement need",
                           "decision_style": "urgency + trust (reviews) + price transparency"},
        "pain_points": ["urgency (something is broken now)", "fear of being overcharged", "scheduling friction"],
        "high_value_triggers": ["equipment failure", "seasonal (HVAC before summer/winter)", "home sale/inspection", "insurance claim"],
        "offer_angles": ["free estimate", "same-day/emergency availability", "transparent flat-rate pricing"],
        "lead_sources": ["local search/maps", "geo-targeted social ads", "referral", "review platforms"],
        "outreach_channels": ["phone (primary)", "SMS confirmation", "email quote follow-up"],
        "ad_angles": ["urgency/emergency availability", "transparent pricing", "before/after result"],
        "landing_page_structure": ["urgency headline + phone CTA above the fold", "service area map", "reviews", "pricing transparency", "single CTA: call or book"],
        "qualification_questions": ["What's the issue?", "How urgent — today, this week, planning ahead?", "Property type/address (service area check)?", "Budget range?"],
        "appointment_setting_logic": {"speed_to_lead": "call within minutes for emergency requests", "no_show_policy": "confirm morning-of"},
        "monetization_model": {"type": "per-job fee, sometimes recurring maintenance contracts", "typical_range": "highly vertical-specific"},
        "risks": ["seasonal demand swings", "licensing/insurance liability", "review-platform dependency for trust"],
    },
    "coaching_consulting": {
        "buyer_profile": {"who": "individual or business seeking expert guidance on a specific outcome (career, business growth, personal transformation)",
                           "decision_style": "trust in the expert + perceived ROI, considered purchase"},
        "pain_points": ["stuck on a specific problem despite effort", "unclear ROI of coaching/consulting spend", "skepticism from past disappointing programs"],
        "high_value_triggers": ["plateaued results", "upcoming decision/deadline", "referral from a peer who got results"],
        "offer_angles": ["free strategy/discovery call", "case study with specific before/after metrics", "money-back or results guarantee"],
        "lead_sources": ["organic content (owned audience)", "referral", "paid social", "webinar/lead magnet"],
        "outreach_channels": ["email nurture sequence", "DM/social", "phone for high-ticket"],
        "ad_angles": ["specific transformation/result", "authority/credibility", "case study"],
        "landing_page_structure": ["outcome-specific headline", "authority/credentials", "case studies with numbers", "program structure", "single CTA: book discovery call"],
        "qualification_questions": ["What outcome are you trying to achieve?", "What have you already tried?", "Timeline and budget?", "Are you the decision-maker?"],
        "appointment_setting_logic": {"speed_to_lead": "within a few hours", "no_show_policy": "confirm 24h before; require a small deposit for high-ticket calls"},
        "monetization_model": {"type": "package/retainer/course fee", "typical_range": "wide — from low-ticket courses to high-ticket 1:1"},
        "risks": ["income/results-claim regulatory exposure", "high-ticket sales cycle requires strong qualification to avoid wasted calls"],
    },
    "luxury_products": {
        "buyer_profile": {"who": "affluent buyer, values exclusivity/craftsmanship/status", "decision_style": "low price sensitivity, high sensitivity to brand experience and authenticity"},
        "pain_points": ["fear of counterfeit/inauthentic product", "wants white-glove experience, not a generic funnel", "scarcity of genuinely differentiated options"],
        "high_value_triggers": ["milestone occasion (anniversary, promotion)", "gifting season", "new release/limited drop"],
        "offer_angles": ["exclusivity/limited availability", "white-glove concierge experience", "provenance/craftsmanship story"],
        "lead_sources": ["curated partnerships", "high-intent search", "invite-only social/referral", "existing client list"],
        "outreach_channels": ["personal outreach (not mass email)", "private client messaging", "in-person/by-appointment"],
        "ad_angles": ["craftsmanship/provenance story", "exclusivity/limited drop", "aspirational lifestyle"],
        "landing_page_structure": ["brand story/heritage", "product craftsmanship detail", "by-appointment or waitlist CTA (not a hard-sell add-to-cart)", "minimal, high-production visual design"],
        "qualification_questions": ["What occasion/use case?", "Prior experience with the brand/category?", "Preferred way to be contacted?"],
        "appointment_setting_logic": {"speed_to_lead": "personal, unhurried follow-up — speed matters less than tone", "no_show_policy": "white-glove reschedule, no penalty framing"},
        "monetization_model": {"type": "high unit margin, low volume", "typical_range": "premium pricing, rarely discounted"},
        "risks": ["brand dilution from over-aggressive discounting/mass marketing", "counterfeit/grey-market reputational risk"],
    },
}


def build_vertical_playbook(vertical: str) -> VerticalPlaybook:
    """Never raises. Unknown verticals return an empty-but-valid playbook
    with the vertical name recorded, rather than raising KeyError."""
    data = _PLAYBOOKS.get(vertical, {})
    return VerticalPlaybook(
        vertical=vertical,
        buyer_profile=data.get("buyer_profile", {}),
        pain_points=list(data.get("pain_points", [])),
        high_value_triggers=list(data.get("high_value_triggers", [])),
        offer_angles=list(data.get("offer_angles", [])),
        lead_sources=list(data.get("lead_sources", [])),
        outreach_channels=list(data.get("outreach_channels", [])),
        ad_angles=list(data.get("ad_angles", [])),
        landing_page_structure=list(data.get("landing_page_structure", [])),
        qualification_questions=list(data.get("qualification_questions", [])),
        appointment_setting_logic=dict(data.get("appointment_setting_logic", {})),
        monetization_model=dict(data.get("monetization_model", {})),
        risks=list(data.get("risks", [])),
    )
