"""backend.stack_planner.planner — recommend_stack, the Stack Planner's
single entry point. Purely advisory: never mutates, never spends, so it
does not call backend.workspaces.live_mode_checklist (unlike
services.ecommerce_operator.launch_guard, which gates real actions)."""
from __future__ import annotations

from backend.costs.compare import compare_stacks
from backend.costs.fixed_cost import stack_fixed_monthly_cost
from backend.costs.payment_cost import payment_fee_rate
from backend.costs.schemas import StackCostEstimate
from backend.costs.stack_total import break_even_client_price, margin_after_stack_cost, stack_total_monthly_cost
from backend.providers import provider_registry

from .recommendations import (
    build_automation_recommendations,
    build_commerce_recommendation,
    build_crm_recommendation,
    build_lead_gen_automation_recommendations,
    build_payment_recommendation,
)
from .schemas import BusinessStackRecommendation
from .strategies import is_lead_gen_strategy, select_strategy

# Hosting is bundled into fixed cost for WooCommerce-based strategies.
_HOSTING_PROVIDER_ID = "hostinger"


def _selections_fixed_cost(selections) -> float:
    return stack_fixed_monthly_cost(selections)


def recommend_stack(request) -> BusinessStackRecommendation:
    """Never raises. Dispatches to the e-commerce or lead-gen branch based
    on the resolved strategy — the two have structurally different stacks
    (checkout+payment vs. CRM+conversation+marketing-automation) rather
    than being squeezed into one shape."""
    strategy_id = select_strategy(request)
    if is_lead_gen_strategy(strategy_id):
        return _recommend_lead_gen_stack(strategy_id, request)
    return _recommend_ecommerce_stack(strategy_id, request)


def _recommend_ecommerce_stack(strategy_id: str, request) -> BusinessStackRecommendation:
    rules_applied: list[str] = [f"strategy={strategy_id}"]

    commerce_rec = build_commerce_recommendation(strategy_id, request)
    payment_rec = build_payment_recommendation(request)
    automation_recs = build_automation_recommendations(request)
    for rec in automation_recs:
        rules_applied.append(f"{rec.provider_id}={'blocked' if rec.blocked else 'allowed'}")

    commerce_provider = provider_registry.get(commerce_rec.provider_id)
    commerce_plan = next(p for p in commerce_provider.plans if p.plan_id == commerce_rec.selected_plan_id)
    selections = [(commerce_provider, commerce_plan)]

    if commerce_rec.provider_id == "woocommerce":
        hosting_provider = provider_registry.get(_HOSTING_PROVIDER_ID)
        hosting_plan = hosting_provider.plans[0]
        selections.append((hosting_provider, hosting_plan))
        commerce_rec.reasons.append(f"Bundled hosting: {hosting_provider.name} ({hosting_plan.display_name}).")

    payment_provider = provider_registry.get(payment_rec.provider_id)
    payment_plan = next(p for p in payment_provider.plans if p.plan_id == payment_rec.selected_plan_id)
    payment_pct, payment_fixed = payment_fee_rate(payment_provider, payment_plan)

    fixed_monthly = _selections_fixed_cost(selections)
    commerce_rec.monthly_cost_estimate = fixed_monthly
    payment_rec.monthly_cost_estimate = 0.0  # payment cost is per-order, not fixed

    margin = margin_after_stack_cost(
        supplier_cost=request.supplier_cost,
        retail_price=request.retail_price,
        payment_pct=payment_pct,
        payment_fixed=payment_fixed,
        stack_fixed_monthly_cost=fixed_monthly,
        expected_monthly_revenue=request.expected_monthly_revenue_usd or 5000.0,
        category=request.category,
    )
    be_price = break_even_client_price(
        supplier_cost=request.supplier_cost or 1.0,
        payment_pct=payment_pct,
        payment_fixed=payment_fixed,
        stack_fixed_monthly_cost=fixed_monthly,
    )
    total_monthly = stack_total_monthly_cost(
        fixed_monthly, payment_pct, payment_fixed,
        request.expected_monthly_orders, request.retail_price,
    )

    cost_estimate = StackCostEstimate(
        stack_id=strategy_id,
        fixed_monthly_cost=fixed_monthly,
        payment_fee_pct=payment_pct,
        payment_fee_fixed=payment_fixed,
        estimated_monthly_orders=request.expected_monthly_orders,
        estimated_avg_order_value=request.retail_price,
        margin_after_stack_cost=margin,
        break_even_client_price=be_price,
        monthly_total_cost_at_volume=total_monthly,
    )

    warnings = [rec.blocked_reason for rec in automation_recs if rec.blocked]

    return BusinessStackRecommendation(
        strategy_id=strategy_id,
        commerce_provider_recommendation=commerce_rec,
        payment_provider_recommendation=payment_rec,
        automation_recommendations=automation_recs,
        monthly_cost_estimate=cost_estimate,
        margin_after_stack_cost=margin,
        break_even_client_price=be_price,
        rules_applied=rules_applied,
        warnings=warnings,
        status="recommended",
    )


def _recommend_lead_gen_stack(strategy_id: str, request) -> BusinessStackRecommendation:
    """No checkout/payment involved — a lead-gen or agency business is
    priced per-lead/retainer, not per-unit margin, so
    backend.validation.margin_calculator's per-order formula doesn't apply
    here. margin_after_stack_cost/break_even_client_price are left at their
    zero defaults with an explicit warning rather than fabricating a
    misleading per-unit number."""
    rules_applied = [f"strategy={strategy_id}"]

    crm_rec = build_crm_recommendation(strategy_id, request)
    rules_applied.append(f"crm:{crm_rec.provider_id}={'blocked' if crm_rec.blocked else 'allowed'}")

    automation_recs = build_automation_recommendations(request, include_gohighlevel=False)
    automation_recs += build_lead_gen_automation_recommendations(strategy_id, request)
    for rec in automation_recs:
        rules_applied.append(f"{rec.provider_id}={'blocked' if rec.blocked else 'allowed'}")

    selections = []
    if not crm_rec.blocked:
        crm_provider = provider_registry.get(crm_rec.provider_id)
        crm_plan = next(p for p in crm_provider.plans if p.plan_id == crm_rec.selected_plan_id)
        selections.append((crm_provider, crm_plan))
        crm_rec.monthly_cost_estimate = _selections_fixed_cost([(crm_provider, crm_plan)])
    for rec in automation_recs:
        if rec.blocked or not rec.selected_plan_id:
            continue
        provider = provider_registry.get(rec.provider_id)
        plan = next(p for p in provider.plans if p.plan_id == rec.selected_plan_id)
        selections.append((provider, plan))
        rec.monthly_cost_estimate = _selections_fixed_cost([(provider, plan)])

    fixed_monthly = _selections_fixed_cost(selections)
    cost_estimate = StackCostEstimate(
        stack_id=strategy_id,
        fixed_monthly_cost=fixed_monthly,
        monthly_total_cost_at_volume=fixed_monthly,
        notes=["Lead-gen/agency strategies price per-lead or per-retainer, not per-unit margin — margin_after_stack_cost/break_even_client_price are not applicable here."],
    )

    warnings = [rec.blocked_reason for rec in automation_recs if rec.blocked]
    if crm_rec.blocked:
        warnings.append(crm_rec.blocked_reason)

    return BusinessStackRecommendation(
        strategy_id=strategy_id,
        crm_provider_recommendation=crm_rec,
        automation_recommendations=automation_recs,
        monthly_cost_estimate=cost_estimate,
        rules_applied=rules_applied,
        warnings=warnings,
        status="recommended",
    )


__all__ = ["recommend_stack", "compare_stacks"]
