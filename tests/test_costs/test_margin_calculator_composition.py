"""Confirm backend.costs composes calculate_margin/suggest_retail_price
rather than duplicating their math: results must be byte-identical to the
base functions when the same effective fee parameters are used, and must
respond monotonically to fee changes."""
from __future__ import annotations

from backend.costs.stack_total import break_even_client_price, margin_after_stack_cost
from backend.validation.margin_calculator import calculate_margin, suggest_retail_price


def test_margin_after_stack_cost_matches_calculate_margin_with_explicit_overrides():
    kwargs = dict(
        supplier_cost=10.0, retail_price=40.0, shipping_cost=2.0,
        monthly_ad_spend=300.0, expected_monthly_revenue=4000.0, category="general",
    )
    direct = calculate_margin(
        **kwargs, payment_fee_pct=0.036, payment_fee_fixed=3.0, platform_monthly_fee=15.0,
    )
    via_costs = margin_after_stack_cost(
        supplier_cost=10.0, retail_price=40.0, shipping_cost=2.0,
        monthly_ad_spend=300.0, expected_monthly_revenue=4000.0, category="general",
        payment_pct=0.036, payment_fixed=3.0, stack_fixed_monthly_cost=15.0,
    )
    assert via_costs == direct


def test_margin_after_stack_cost_omitted_overrides_match_default_calculate_margin():
    """When callers use backend.costs but the stack happens to carry the
    same fee numbers as the env defaults, the reading is identical — proof
    there is no separate formula living in backend.costs."""
    from backend.validation import margin_calculator as mc

    via_costs = margin_after_stack_cost(
        supplier_cost=10.0, retail_price=40.0,
        payment_pct=mc._PAYMENT_FEE_PCT, payment_fixed=mc._PAYMENT_FEE_FIXED,
        stack_fixed_monthly_cost=mc._PLATFORM_MONTHLY,
    )
    default = calculate_margin(supplier_cost=10.0, retail_price=40.0)
    assert via_costs == default


def test_break_even_client_price_matches_suggest_retail_price():
    direct = suggest_retail_price(
        landed_cost=12.0, target_net_margin_pct=25.0,
        payment_fee_pct=0.03, payment_fee_fixed=1.0, platform_monthly_fee=10.0,
    )
    via_costs = break_even_client_price(
        supplier_cost=12.0, target_net_margin_pct=25.0,
        payment_pct=0.03, payment_fixed=1.0, stack_fixed_monthly_cost=10.0,
    )
    assert via_costs == direct


def test_higher_fixed_cost_never_increases_net_margin():
    cheap = margin_after_stack_cost(
        supplier_cost=10.0, retail_price=40.0,
        payment_pct=0.03, payment_fixed=0.3, stack_fixed_monthly_cost=5.0,
    )
    expensive = margin_after_stack_cost(
        supplier_cost=10.0, retail_price=40.0,
        payment_pct=0.03, payment_fixed=0.3, stack_fixed_monthly_cost=500.0,
    )
    assert expensive["net_margin"] <= cheap["net_margin"]
