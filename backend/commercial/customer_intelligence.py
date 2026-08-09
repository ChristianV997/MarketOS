from __future__ import annotations

from typing import Any


_PLAYBOOKS = {
    "ecommerce_brand": ("Online shoppers with a clear problem or preference in the selected category.", ["problem-aware", "comparison shoppers", "repeat-purchase potential"], ["unclear differentiation", "trust and delivery friction"]),
    "clinic_wellness": ("Adults seeking a credible, convenient wellness outcome.", ["prevention-oriented", "symptom-aware", "follow-up seekers"], ["trust", "safety", "claims compliance"]),
    "home_services": ("Property owners needing a reliable local service with low coordination effort.", ["urgent need", "planned maintenance", "property managers"], ["response time", "proof of work", "price uncertainty"]),
    "real_estate": ("Buyers or sellers with a defined location, budget, and timing.", ["first-time buyers", "investors", "move-up households"], ["financing", "trust", "long consideration cycle"]),
    "car_sales": ("Vehicle shoppers comparing total ownership value and financing options.", ["replacement buyers", "budget-conscious", "feature-driven"], ["financing", "inventory", "dealer trust"]),
    "coaching_consulting": ("Professionals or owners seeking a measurable improvement with expert guidance.", ["urgent outcome", "self-directed evaluators", "referral-led"], ["proof", "scope clarity", "outcome attribution"]),
    "luxury_products": ("Discerning buyers who value provenance, quality, and service over lowest price.", ["heritage/value", "gift buyers", "collector-minded"], ["authenticity", "service", "exclusivity"]),
    "general": ("A clearly defined audience with a validated problem and ability to pay.", ["problem-aware", "comparison shoppers", "referral-led"], ["unclear problem", "trust", "weak differentiation"]),
}


def run_customer_intelligence(business_type: str, vertical: str = "general", target_geo: str = "MX",
                              category: str = "general", dry_run: bool = True,
                              read_only: bool = True) -> dict[str, Any]:
    if not dry_run or not read_only:
        raise PermissionError("customer intelligence MVP is read-only and dry-run only")
    vertical_value = str(vertical or "general").strip().lower()
    if vertical_value not in _PLAYBOOKS: vertical_value = "general"
    icp, segment_names, pain_points = _PLAYBOOKS[vertical_value]
    segments = [{"name": name, "evidence_status": "not_connected", "priority": index + 1} for index, name in enumerate(segment_names)]
    return {
        "business_type": str(business_type or "general").strip() or "general",
        "vertical": vertical_value, "target_geo": str(target_geo or "MX").strip().upper() or "MX",
        "category": str(category or "general").strip() or "general", "status": "ready_for_dry_run",
        "icp": {"description": icp, "evidence_status": "hypothesis_only"}, "segments": segments,
        "pain_points": pain_points,
        "offer_angles": ["clarity of outcome", "proof and trust", "lower friction next step"],
        "lead_sources": [{"source": source, "status": "not_connected"} for source in ["search intent", "social content", "referrals", "partnerships"]],
        "qualification_questions": ["What outcome are you trying to achieve?", "Why now?", "What constraints or budget range apply?"],
        "risk_flags": ["hypothesis_not_validated", "no_customer_data_connected"],
        "next_actions": ["Interview or survey representative prospects.", "Validate segment language with approved evidence.", "Test one offer angle in a dry-run experiment matrix."],
        "provenance": {"customer_data": "not_connected", "method": "deterministic_vertical_playbook"}, "dry_run": True,
    }
