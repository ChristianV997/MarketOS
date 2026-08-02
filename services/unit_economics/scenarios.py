"""services.unit_economics.scenarios — price_sensitivity_grid.

Thin re-run loop over calculate_margin; zero new margin math.
"""
from __future__ import annotations

from typing import Any

from backend.validation.margin_calculator import calculate_margin


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
        margin = calculate_margin(
            supplier_cost=supplier_cost, retail_price=price,
            shipping_cost=shipping_cost, category=category,
        )
        rows.append({"price_delta_pct": round(delta * 100, 1), "retail_price": price, "margin": margin})
    return rows
