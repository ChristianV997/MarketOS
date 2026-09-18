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

from decimal import Decimal

from backend.economics import Money, UnitEconomicsAssumptions
from backend.economics import calculate_unit_economics as calculate_canonical_unit_economics


def _canonical_legacy_contribution(
    supplier_cost: float,
    retail_price: float,
    shipping_cost: float,
    expected_monthly_revenue: float,
    return_rate: float | None,
    category: str,
) -> Decimal:
    """Adapt the legacy monthly assumptions into the canonical kernel."""
    from backend.validation.margin_calculator import CATEGORY_RETURN_RATES, _PAYMENT_FEE_FIXED, _PAYMENT_FEE_PCT, _PLATFORM_MONTHLY

    if retail_price <= 0:
        return Decimal("0")
    expected_orders = max(Decimal(str(expected_monthly_revenue)) / Decimal(str(retail_price)), Decimal("1"))
    resolved_return = Decimal(str(return_rate if return_rate is not None else CATEGORY_RETURN_RATES.get(category, CATEGORY_RETURN_RATES["general"])))
    result = calculate_canonical_unit_economics(
        Money(retail_price, "USD", source="legacy_break_even", provenance="assumed"),
        Money(max(supplier_cost, 0.0), "USD", source="legacy_break_even", provenance="assumed"),
        assumptions=UnitEconomicsAssumptions(
            supplier_shipping=Money(max(shipping_cost, 0.0), "USD", source="legacy_break_even", provenance="assumed"),
            payment_fee_rate=Decimal(str(_PAYMENT_FEE_PCT)),
            payment_fee_fixed=Money(_PAYMENT_FEE_FIXED, "USD", source="legacy_break_even", provenance="assumed"),
            platform_fee_fixed=Money(Decimal(str(_PLATFORM_MONTHLY)) / expected_orders, "USD", source="legacy_break_even", provenance="assumed"),
            platform_fee_rate=Decimal("0"),
            return_rate=Decimal("0"),
        ),
    )
    gross_margin = Decimal(str(retail_price)) - Decimal(str(max(supplier_cost, 0.0))) - Decimal(str(max(shipping_cost, 0.0)))
    return result.contribution_before_cac.amount - (gross_margin * resolved_return)


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
    contribution = _canonical_legacy_contribution(supplier_cost, retail_price, shipping_cost, expected_monthly_revenue, return_rate, category)
    return max(0.0, round(float(contribution), 2))


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
