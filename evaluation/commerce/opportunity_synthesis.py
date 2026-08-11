"""Small deterministic bridge between demand and supplier feasibility reports."""
from __future__ import annotations

from typing import Any, Mapping


def _bounded(value: Any) -> float:
    try:
        return round(max(0.0, min(1.0, float(value or 0))), 4)
    except (TypeError, ValueError):
        return 0.0


def synthesize_opportunities(
    marketplace_report: Mapping[str, Any] | None,
    supplier_report: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Join existing report candidates without creating a third scoring engine."""
    market = {item.get("candidate_id"): item for item in (marketplace_report or {}).get("candidates", []) if item.get("candidate_id")}
    supplier = {item.get("candidate_id"): item for item in (supplier_report or {}).get("candidates", []) if item.get("candidate_id")}
    results = []
    for candidate_id in sorted(set(market) | set(supplier)):
        market_score = (market.get(candidate_id) or {}).get("score", {})
        supplier_score = (supplier.get(candidate_id) or {}).get("score", {})
        marketplace_opportunity = _bounded(market_score.get("overall_marketplace_opportunity"))
        supplier_feasibility = _bounded(supplier_score.get("overall_supplier_feasibility"))
        combined = round(marketplace_opportunity * 0.55 + supplier_feasibility * 0.45, 4)
        supplier_recommendation = supplier_score.get("recommendation", "validate_live_supplier_first")
        if supplier_recommendation.startswith("reject"):
            recommendation = supplier_recommendation
        elif not supplier.get(candidate_id):
            recommendation = "validate_live_supplier_first"
        elif combined >= 0.68:
            recommendation = "advance_to_launch_draft"
        else:
            recommendation = supplier_recommendation
        next_action = f"{recommendation}:{candidate_id}"
        results.append({"candidate_id": candidate_id, "marketplace_opportunity": marketplace_opportunity, "supplier_feasibility": supplier_feasibility, "combined_opportunity": combined, "combined_recommendation": recommendation, "next_best_action": next_action})
    return sorted(results, key=lambda item: (-item["combined_opportunity"], item["candidate_id"]))


def build_synthesis_report(marketplace_report: Mapping[str, Any] | None, supplier_report: Mapping[str, Any] | None) -> dict[str, Any]:
    candidates = synthesize_opportunities(marketplace_report, supplier_report)
    return {"report_version": "opportunity-synthesis-v1", "candidate_count": len(candidates), "top_candidate_id": candidates[0]["candidate_id"] if candidates else None, "next_best_action": candidates[0]["next_best_action"] if candidates else "validate_live_supplier_first", "candidates": candidates, "read_only": True, "network_calls": False, "mutated": False}
