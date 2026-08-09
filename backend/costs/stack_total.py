"""backend.costs.stack_total — total monthly cost and margin-after-stack-cost.

margin_after_stack_cost and break_even_client_price are one-line
compositions of backend.validation.margin_calculator's calculate_margin/
suggest_retail_price (using the optional payment_fee_pct/payment_fee_fixed/
platform_monthly_fee overrides added for the Cost Engine) — no fee/margin
formula is reimplemented here.
"""
from __future__ import annotations

from backend.validation.margin_calculator import calculate_margin, suggest_retail_price


def stack_total_monthly_cost(
    fixed_monthly: float,
    payment_pct: float,
    payment_fixed: float,
    estimated_monthly_orders: float,
    estimated_avg_order_value: float,
) -> float:
    """Fixed monthly cost plus estimated payment-processing cost at the
    given order volume. Pure arithmetic — no external calls."""
    payment_cost = estimated_monthly_orders * (estimated_avg_order_value * payment_pct + payment_fixed)
    return round(fixed_monthly + payment_cost, 2)


def margin_after_stack_cost(
    supplier_cost: float,
    retail_price: float,
    *,
    payment_pct: float,
    payment_fixed: float,
    stack_fixed_monthly_cost: float,
    shipping_cost: float = 0.0,
    monthly_ad_spend: float = 500.0,
    expected_monthly_revenue: float = 5000.0,
    return_rate: float | None = None,
    category: str = "general",
) -> dict:
    return calculate_margin(
        supplier_cost=supplier_cost,
        retail_price=retail_price,
        shipping_cost=shipping_cost,
        monthly_ad_spend=monthly_ad_spend,
        expected_monthly_revenue=expected_monthly_revenue,
        return_rate=return_rate,
        category=category,
        payment_fee_pct=payment_pct,
        payment_fee_fixed=payment_fixed,
        platform_monthly_fee=stack_fixed_monthly_cost,
    )


def break_even_client_price(
    supplier_cost: float,
    *,
    payment_pct: float,
    payment_fixed: float,
    stack_fixed_monthly_cost: float,
    target_net_margin_pct: float = 20.0,
    monthly_ad_spend: float = 500.0,
    expected_monthly_revenue: float = 5000.0,
    return_rate: float = 0.12,
) -> float:
    return suggest_retail_price(
        landed_cost=supplier_cost,
        target_net_margin_pct=target_net_margin_pct,
        monthly_ad_spend=monthly_ad_spend,
        expected_monthly_revenue=expected_monthly_revenue,
        return_rate=return_rate,
        payment_fee_pct=payment_pct,
        payment_fee_fixed=payment_fixed,
        platform_monthly_fee=stack_fixed_monthly_cost,
    )
