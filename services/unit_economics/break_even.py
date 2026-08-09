"""services.unit_economics.break_even — break_even_cac/required_roas.

Derived directly from backend.validation.margin_calculator.calculate_margin's
verified formula (net_margin = gross_margin - payment_fee - platform_fee -
return_loss - cac): calling it with monthly_ad_spend=0.0 forces cac=0, so
the resulting net_margin equals exactly the max CAC a unit can absorb
before net margin goes negative — i.e. break-even CAC. No margin math is
duplicated here.

expected_monthly_revenue defaults to calculate_margin's own default
(5000.0) rather than being forced to retail_price: platform_fee amortizes
a *monthly* fixed subscription cost over expected_orders, so pinning
expected_orders to 1 (by setting expected_monthly_revenue=retail_price)
dumps the entire monthly fee onto a single unit and understates break-even
CAC by an order of magnitude. Passing a realistic monthly-volume figure
(or leaving the default) amortizes it the same way calculate_margin's own
"normal" callers already do.
"""
from __future__ import annotations

from backend.validation.margin_calculator import calculate_margin


def break_even_cac(
    supplier_cost: float,
    retail_price: float,
    shipping_cost: float = 0.0,
    expected_monthly_revenue: float = 5000.0,
    return_rate: float | None = None,
    category: str = "general",
) -> float:
    """Max CAC this unit can absorb before net margin goes negative, at the
    given expected monthly sales volume (defaults to calculate_margin's own
    default of $5000/mo)."""
    contribution = calculate_margin(
        supplier_cost=supplier_cost,
        retail_price=retail_price,
        shipping_cost=shipping_cost,
        monthly_ad_spend=0.0,
        expected_monthly_revenue=expected_monthly_revenue,
        return_rate=return_rate,
        category=category,
    )
    return max(0.0, round(contribution["net_margin"], 2))


def required_roas(
    supplier_cost: float,
    retail_price: float,
    shipping_cost: float = 0.0,
    expected_monthly_revenue: float = 5000.0,
    return_rate: float | None = None,
    category: str = "general",
) -> float:
    """retail_price / break_even_cac — the minimum ROAS this unit needs to
    not lose money on acquisition. inf when break_even_cac is 0 (any spend
    at all would already be unaffordable)."""
    cac = break_even_cac(supplier_cost, retail_price, shipping_cost, expected_monthly_revenue, return_rate, category)
    if cac <= 0:
        return float("inf")
    return round(retail_price / cac, 4)


def verdict_from_margin(margin: dict) -> str:
    return margin.get("margin_status", "unknown")
