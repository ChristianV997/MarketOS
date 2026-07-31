"""backend.stack_planner.recommendations — hard business-rule predicates and
ProviderRecommendation builders for the Stack Planner.

Gated providers (GoHighLevel, Postiz, n8n) are still surfaced in the
recommendation output when blocked, with `blocked=True` and a
`blocked_reason` — the hard rules never silently omit a gated provider,
they explain why it isn't recommended.
"""
from __future__ import annotations

from backend.providers import provider_registry
from backend.providers.schemas import ProviderRecommendation


def gohighlevel_allowed(request) -> bool:
    """No GoHighLevel recommendation below the cheapest plan's revenue
    threshold — its fixed cost isn't justified until client revenue clears
    it."""
    ghl = provider_registry.get("gohighlevel")
    cheapest_threshold = min(plan.min_monthly_revenue_usd for plan in ghl.plans)
    return request.expected_monthly_revenue_usd >= cheapest_threshold


def shopify_allowed_over_woo(request) -> bool:
    """No Shopify recommendation when Hostinger+WooCommerce is sufficient
    and the request is margin-sensitive (low_cost_validation)."""
    return request.margin_sensitivity != "low_cost_validation"


def n8n_allowed(request) -> bool:
    """n8n stays internal-only — never recommended for a white-labeled,
    client-facing product (existing governance: docs/oss/LICENSE_MANIFEST.yml)."""
    return not request.is_white_labeled_client_facing


def postiz_allowed(request) -> bool:
    """Postiz (AGPL-3.0) is never recommended without an explicit
    legal-approval flag."""
    return bool(request.postiz_legal_approval)


def _cheapest_plan(provider):
    return min(provider.plans, key=lambda p: sum(c.amount for c in p.cost_components if c.kind == "fixed_monthly"))


def build_commerce_recommendation(strategy_id: str, request) -> ProviderRecommendation:
    if strategy_id == "client_ecommerce_shopify_premium" and shopify_allowed_over_woo(request):
        shopify = provider_registry.get("shopify")
        eligible = [p for p in shopify.plans if request.expected_monthly_revenue_usd >= p.min_monthly_revenue_usd]
        plan = max(eligible, key=lambda p: p.min_monthly_revenue_usd) if eligible else shopify.plans[0]
        return ProviderRecommendation(
            provider_id="shopify", category="commerce_platform", selected_plan_id=plan.plan_id,
            reasons=["Shopify selected: checkout/app-ecosystem needs or brand premium justify the higher fixed cost."],
        )
    if strategy_id == "marketos_owned_stack":
        medusa = provider_registry.get("medusa")
        plan = medusa.plans[0]
        return ProviderRecommendation(
            provider_id="medusa", category="headless_commerce", selected_plan_id=plan.plan_id,
            reasons=["Medusa selected: MarketOS-owned, self-hosted commerce path."],
        )
    woo = provider_registry.get("woocommerce")
    plan = woo.plans[0]
    reasons = ["Hostinger+WooCommerce selected: lowest fixed cost, sufficient for validation-stage or margin-sensitive commerce."]
    if strategy_id == "client_ecommerce_shopify_premium" and not shopify_allowed_over_woo(request):
        reasons.append("Shopify was requested but rejected: margin_sensitivity=low_cost_validation makes WooCommerce sufficient.")
    return ProviderRecommendation(provider_id="woocommerce", category="commerce_platform", selected_plan_id=plan.plan_id, reasons=reasons)


def build_payment_recommendation(request) -> ProviderRecommendation:
    if request.target_geo == "MX":
        mp = provider_registry.get("mercado_pago_mx")
        plan = mp.plans[0]
        return ProviderRecommendation(
            provider_id="mercado_pago_mx", category="payment_processor", selected_plan_id=plan.plan_id,
            reasons=["Mercado Pago preferred in MX: regional buyer trust and marginally lower blended fee than Stripe MX."],
        )
    stripe = provider_registry.get("stripe_mx")
    plan = stripe.plans[0]
    return ProviderRecommendation(
        provider_id="stripe_mx", category="payment_processor", selected_plan_id=plan.plan_id,
        reasons=[f"Stripe selected as the default processor for target_geo={request.target_geo}."],
    )


def build_automation_recommendations(request) -> list[ProviderRecommendation]:
    recs: list[ProviderRecommendation] = []

    if n8n_allowed(request):
        recs.append(ProviderRecommendation(
            provider_id="n8n", category="workflow_automation", selected_plan_id="internal",
            reasons=["n8n available for internal operational automation (notifications, CRM sync, exports)."],
        ))
    else:
        recs.append(ProviderRecommendation(
            provider_id="n8n", category="workflow_automation", blocked=True,
            blocked_reason="n8n is internal-only per existing governance; never recommended for a white-labeled, client-facing product.",
        ))

    if gohighlevel_allowed(request):
        ghl = provider_registry.get("gohighlevel")
        eligible = [p for p in ghl.plans if request.expected_monthly_revenue_usd >= p.min_monthly_revenue_usd]
        plan = max(eligible, key=lambda p: p.min_monthly_revenue_usd)
        recs.append(ProviderRecommendation(
            provider_id="gohighlevel", category="crm", selected_plan_id=plan.plan_id,
            reasons=[f"Client revenue (${request.expected_monthly_revenue_usd:,.0f}/mo) clears the {plan.plan_id} plan's ${plan.min_monthly_revenue_usd:,.0f}/mo threshold."],
        ))
    else:
        cheapest_threshold = min(p.min_monthly_revenue_usd for p in provider_registry.get("gohighlevel").plans)
        recs.append(ProviderRecommendation(
            provider_id="gohighlevel", category="crm", blocked=True,
            blocked_reason=f"Expected revenue is below GoHighLevel's cheapest plan threshold (${cheapest_threshold:,.0f}/mo).",
        ))

    if postiz_allowed(request):
        recs.append(ProviderRecommendation(
            provider_id="postiz", category="social_publishing", selected_plan_id="sidecar",
            reasons=["Postiz legal approval flag set; usable as a social-publishing sidecar."],
        ))
    else:
        recs.append(ProviderRecommendation(
            provider_id="postiz", category="social_publishing", blocked=True,
            blocked_reason="Postiz (AGPL-3.0) requires explicit legal approval (postiz_legal_approval=True); not granted.",
        ))

    return recs
