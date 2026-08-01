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


def build_gohighlevel_recommendation(request) -> ProviderRecommendation:
    if gohighlevel_allowed(request):
        ghl = provider_registry.get("gohighlevel")
        eligible = [p for p in ghl.plans if request.expected_monthly_revenue_usd >= p.min_monthly_revenue_usd]
        plan = max(eligible, key=lambda p: p.min_monthly_revenue_usd)
        return ProviderRecommendation(
            provider_id="gohighlevel", category="crm", selected_plan_id=plan.plan_id,
            reasons=[f"Client revenue (${request.expected_monthly_revenue_usd:,.0f}/mo) clears the {plan.plan_id} plan's ${plan.min_monthly_revenue_usd:,.0f}/mo threshold."],
        )
    cheapest_threshold = min(p.min_monthly_revenue_usd for p in provider_registry.get("gohighlevel").plans)
    return ProviderRecommendation(
        provider_id="gohighlevel", category="crm", blocked=True,
        blocked_reason=f"Expected revenue is below GoHighLevel's cheapest plan threshold (${cheapest_threshold:,.0f}/mo).",
    )


def build_automation_recommendations(request, *, include_gohighlevel: bool = True) -> list[ProviderRecommendation]:
    """`include_gohighlevel=False` is used by lead-gen strategies, which
    already represent GoHighLevel via `crm_provider_recommendation` — listing
    it again here would be a duplicate, not a second independent gate."""
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

    if include_gohighlevel:
        recs.append(build_gohighlevel_recommendation(request))

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


def build_crm_recommendation(strategy_id: str, request) -> ProviderRecommendation:
    """Only called for lead-gen/agency strategies. `high_ticket_lead_gen_low_cost`
    reports the CRM gap honestly (Twenty is deferred pending legal review —
    AGPL-3.0) rather than recommending it or fabricating a substitute."""
    if strategy_id in ("high_ticket_lead_gen_gohighlevel_fast", "agency_white_label_fast"):
        return build_gohighlevel_recommendation(request)
    return ProviderRecommendation(
        provider_id="twenty", category="crm", blocked=True,
        blocked_reason=(
            "Twenty CRM (the catalog's one low-cost CRM candidate) is AGPL-3.0 "
            "and deferred pending legal review — no CRM adapter is recommended "
            "for the low-cost lead-gen stack this pass. Consider GoHighLevel "
            "once expected revenue clears its threshold (see warnings)."
        ),
    )


def build_lead_gen_automation_recommendations(strategy_id: str, request) -> list[ProviderRecommendation]:
    """Chatwoot + Mautic fill the conversation/marketing-automation gap left
    by Twenty's deferral for the low-cost strategy. GoHighLevel-based
    strategies already bundle conversation + marketing automation, so no
    extra entries are needed there."""
    if strategy_id != "high_ticket_lead_gen_low_cost":
        return []
    chatwoot = provider_registry.get("chatwoot")
    mautic = provider_registry.get("mautic")
    return [
        ProviderRecommendation(
            provider_id="chatwoot", category="conversation_inbox", selected_plan_id=chatwoot.plans[0].plan_id,
            reasons=["Self-hosted conversation inbox for lead qualification at near-zero fixed cost."],
        ),
        ProviderRecommendation(
            provider_id="mautic", category="marketing_automation", selected_plan_id=mautic.plans[0].plan_id,
            reasons=["Self-hosted email/segment automation for lead nurture at near-zero fixed cost."],
        ),
    ]
