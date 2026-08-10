"""Manual landing-page export packet; it contains no publishing client."""
from __future__ import annotations
from .models import LandingPagePacket, OpportunityCandidate


def build_landing_page_packet(candidate: OpportunityCandidate, target_builder: str = "gempages") -> LandingPagePacket:
    return LandingPagePacket(candidate.candidate_id, target_builder, f"Draft: Explore {candidate.product_name} for a practical use case", "Draft offer: validate product details, price, and fulfillment before publishing.",
        ("Draft benefit: frame the use case, not a guaranteed outcome.", "Draft benefit: explain product details only after supplier evidence is reviewed."),
        ("Proof required: product-specific photos, specifications, supplier documentation, and permitted customer evidence.",),
        ("What is included? Confirm with supplier evidence before publishing.", "When will it arrive? Add verified fulfillment information only."),
        ("Objection response draft: do not promise results; show verifiable specifications and clear policies."), "Review the draft and verify product details",
        ("No claim is approved by this packet.", "No scarcity, testimonial, medical, safety, ranking, income, ROAS, or guaranteed-result claim."),
        ("Verified product images", "Verified specifications", "Policy copy", "Permissioned proof if used"),
        ("Human review of every claim", "Verify product/supplier/price data", "Create page manually in chosen builder", "Do not publish until approval packet is completed"))
