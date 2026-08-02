from __future__ import annotations

from backend.costs.compare import compare_stacks
from backend.costs.fixed_cost import stack_fixed_monthly_cost
from backend.costs.payment_cost import payment_fee_rate, payment_processing_cost_per_order
from backend.costs.schemas import StackCostEstimate
from backend.providers import provider_registry


def test_stack_fixed_monthly_cost_sums_across_selections():
    hostinger = provider_registry.get("hostinger")
    woo = provider_registry.get("woocommerce")
    selections = [
        (hostinger, hostinger.plans[0]),
        (woo, woo.plans[0]),
    ]
    total = stack_fixed_monthly_cost(selections)
    assert total == hostinger.plans[0].cost_components[0].amount


def test_payment_fee_rate_extraction():
    stripe_mx = provider_registry.get("stripe_mx")
    pct, fixed = payment_fee_rate(stripe_mx, stripe_mx.plans[0])
    assert pct > 0
    assert fixed >= 0
    cost = payment_processing_cost_per_order(stripe_mx, stripe_mx.plans[0], 200.0)
    assert cost == round(200.0 * pct + fixed, 2)


def test_woocommerce_has_no_payment_fee_component():
    woo = provider_registry.get("woocommerce")
    pct, fixed = payment_fee_rate(woo, woo.plans[0])
    assert pct == 0.0 and fixed == 0.0


def test_compare_stacks_picks_cheapest_and_highest_margin():
    cheap = StackCostEstimate(
        stack_id="cheap", monthly_total_cost_at_volume=50.0,
        margin_after_stack_cost={"net_margin_pct": 10.0},
    )
    pricey_but_high_margin = StackCostEstimate(
        stack_id="premium", monthly_total_cost_at_volume=500.0,
        margin_after_stack_cost={"net_margin_pct": 30.0},
    )
    result = compare_stacks([cheap, pricey_but_high_margin])
    assert result.cheapest_stack_id == "cheap"
    assert result.highest_margin_stack_id == "premium"


def test_compare_stacks_empty_list_never_raises():
    result = compare_stacks([])
    assert result.stacks == []
    assert result.cheapest_stack_id == ""
