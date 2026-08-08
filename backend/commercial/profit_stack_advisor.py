from __future__ import annotations

from typing import Any


def run_profit_stack_advisor(business_name: str, business_model: str = "own_ecommerce", target_geo: str = "MX",
                             expected_monthly_revenue: float = 0.0, expected_monthly_orders: float = 0.0,
                             margin_sensitivity: str = "standard", is_white_labeled_client_facing: bool = False,
                             dry_run: bool = True, read_only: bool = True) -> dict[str, Any]:
    if not dry_run or not read_only:
        raise PermissionError("profit stack advisor MVP is read-only and dry-run only")
    revenue = max(float(expected_monthly_revenue or 0.0), 0.0)
    orders = max(float(expected_monthly_orders or 0.0), 0.0)
    low_cost = revenue < 5000 or str(margin_sensitivity).lower() in {"high", "strict", "sensitive"}
    simple = revenue >= 25000 or orders >= 500
    commerce = "low_cost_headless_or_woocommerce_candidate" if low_cost else "shopify_style_managed_candidate" if simple else "managed_or_low_cost_commerce_candidate"
    blocked = ["live_provider_selection_not_connected", "provider_prices_not_live"]
    if is_white_labeled_client_facing: blocked.append("white_label_legal_and_brand_review_required")
    return {
        "business_name": str(business_name or "").strip(), "business_model": str(business_model or "own_ecommerce").strip(),
        "target_geo": str(target_geo or "MX").strip().upper() or "MX", "status": "ready_for_dry_run",
        "recommended_stack": {"commerce": commerce, "payments": "Mercado_Pago_candidate_LATAM_or_existing_approved_provider", "automation": "n8n_internal_only_candidate", "analytics": "GA4_or_PostHog_candidate"},
        "cost_assumptions": {"expected_monthly_revenue": revenue, "expected_monthly_orders": orders, "margin_sensitivity": margin_sensitivity, "pricing_provenance": "static_estimates_or_not_connected"},
        "blocked_providers": blocked,
        "rationale": ["Recommendation is a deterministic fit heuristic, not a provider quote.", "Keep provider selection behind explicit legal, credential, and integration review."],
        "risk_flags": ["no_live_provider_pricing", "no_provider_credentials_verified"] + (["white_label_review_required"] if is_white_labeled_client_facing else []),
        "next_actions": ["Compare current provider pricing and terms manually.", "Validate payment availability for the target geography.", "Confirm white-label and commercial licensing before adoption."],
        "provenance": {"provider_prices": "static_estimates_or_not_connected", "method": "deterministic_stack_fit_heuristic"}, "dry_run": True,
    }
