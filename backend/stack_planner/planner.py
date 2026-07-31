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

from .recommendations import build_automation_recommendations, build_commerce_recommendation, build_payment_recommendation
from .schemas import BusinessStackRecommendation
from .strategies import is_deferred_strategy, select_strategy

# Hosting is bundled into fixed cost for WooCommerce-based strategies (no
# HostingPort/adapter exists yet — Phase 2 — but the catalog cost is real
# and cheap to include today).
_HOSTING_PROVIDER_ID = "hostinger"


def recommend_stack(request) -> BusinessStackRecommendation:
    """Never raises. Deferred strategies (needing CRM/Conversation providers
    this increment doesn't model) return an explicit `status="not_yet_supported"`
    result rather than a partial or fabricated recommendation."""
    strategy_id = select_strategy(request)

    if is_deferred_strategy(strategy_id):
        return BusinessStackRecommendation(
            strategy_id=strategy_id,
            status="not_yet_supported",
            warnings=[
                f"Strategy '{strategy_id}' requires CRM/Conversation providers not yet modeled "
                "in this Stack Planner increment (see docs/COST_AWARE_INTEGRATION_AUDIT.md's Phase 2 list).",
            ],
        )

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

    fixed_monthly = stack_fixed_monthly_cost(selections)
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


__all__ = ["recommend_stack", "compare_stacks"]
