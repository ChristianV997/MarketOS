"""services.unit_economics.scenarios — price_sensitivity_grid.

Thin re-run loop over calculate_margin; zero new margin math.
"""
from __future__ import annotations

from typing import Any

from decimal import Decimal

from backend.economics import Money, UnitEconomicsAssumptions
from backend.economics import calculate_unit_economics as calculate_canonical_unit_economics


def _scenario_margin(supplier_cost: float, retail_price: float, shipping_cost: float, category: str) -> dict[str, Any]:
    from backend.validation.margin_calculator import CATEGORY_RETURN_RATES, _PAYMENT_FEE_FIXED, _PAYMENT_FEE_PCT, _PLATFORM_MONTHLY

    expected_orders = max(Decimal("5000") / Decimal(str(retail_price)), Decimal("1")) if retail_price > 0 else Decimal("1")
    result = calculate_canonical_unit_economics(
        Money(max(retail_price, 0.0), "USD", source="legacy_sensitivity", provenance="assumed"),
        Money(max(supplier_cost, 0.0), "USD", source="legacy_sensitivity", provenance="assumed"),
        assumptions=UnitEconomicsAssumptions(
            supplier_shipping=Money(max(shipping_cost, 0.0), "USD", source="legacy_sensitivity", provenance="assumed"),
            payment_fee_rate=Decimal(str(_PAYMENT_FEE_PCT)),
            payment_fee_fixed=Money(_PAYMENT_FEE_FIXED, "USD", source="legacy_sensitivity", provenance="assumed"),
            platform_fee_fixed=Money(Decimal(str(_PLATFORM_MONTHLY)) / expected_orders, "USD", source="legacy_sensitivity", provenance="assumed"),
            platform_fee_rate=Decimal("0"),
            return_rate=Decimal(str(CATEGORY_RETURN_RATES.get(category, CATEGORY_RETURN_RATES["general"]))),
            cac=Money(Decimal("500") / expected_orders, "USD", source="legacy_sensitivity", provenance="assumed"),
        ),
    )
    margin_pct = result.contribution_margin_after_cac * Decimal("100") if result.contribution_margin_after_cac is not None else Decimal("0")
    status = "profitable" if margin_pct > Decimal("15") else "breakeven" if margin_pct > Decimal("5") else "loss"
    return {
        "supplier_cost": round(supplier_cost, 2), "retail_price": round(retail_price, 2),
        "landed_cost": round(float(result.product_cost.amount + result.supplier_shipping.amount), 2),
        "gross_margin": round(float(result.contribution_before_cac.amount + result.return_reserve.amount + result.cac.amount), 2),
        "payment_fee": round(float(result.payment_fees.amount), 2),
        "platform_fee": round(float(result.platform_fees.amount), 2),
        "return_loss": round(float(result.return_reserve.amount), 2),
        "cac": round(float(result.cac.amount), 2),
        "net_margin": round(float(result.contribution_after_cac.amount), 2),
        "net_margin_pct": round(float(margin_pct), 1), "margin_status": status,
    }


def price_sensitivity_grid(
    supplier_cost: float,
    retail_price: float,
    *,
    shipping_cost: float = 0.0,
    deltas: tuple[float, ...] = (-0.1, 0.0, 0.1),
    category: str = "general",
) -> list[dict[str, Any]]:
    rows = []
    for delta in deltas:
        price = round(retail_price * (1 + delta), 2)
        margin = _scenario_margin(supplier_cost, price, shipping_cost, category)
        rows.append({"price_delta_pct": round(delta * 100, 1), "retail_price": price, "margin": margin})
    return rows
