from __future__ import annotations

from typing import Any


def run_product_research(product_name: str, category: str = "general", target_geo: str = "MX",
                         retail_price: float | None = None, dry_run: bool = True,
                         read_only: bool = True) -> dict[str, Any]:
    """Return an input-only product research scaffold.

    This intentionally does not claim demand, competition, supplier quality,
    or ROAS. Those fields are explicitly marked unconnected until evidence
    providers are added behind reviewed contracts.
    """
    if not dry_run or not read_only:
        raise PermissionError("product research MVP is read-only and dry-run only")
    name = str(product_name or "").strip()
    category_value = str(category or "general").strip().lower() or "general"
    geo = str(target_geo or "MX").strip().upper() or "MX"
    risk_flags: list[str] = []
    next_actions = ["Connect approved demand evidence before making a launch decision.",
                    "Validate supplier cost, shipping time, inventory, and return policy.",
                    "Run a human-reviewed competitor and audience research pass."]
    if not name: risk_flags.append("missing_product_name")
    if retail_price is None or retail_price <= 0:
        risk_flags.append("missing_retail_price")
    if category_value == "general": risk_flags.append("unspecified_category")
    price_band = "unknown"
    if retail_price is not None and retail_price > 0:
        price_band = "entry" if retail_price < 300 else "mid" if retail_price < 1200 else "premium"
    assumed_landed_cost = round(float(retail_price) * 0.35, 2) if retail_price and retail_price > 0 else None
    assumed_margin = round((float(retail_price) - assumed_landed_cost) / float(retail_price), 4) if assumed_landed_cost is not None else None
    recommendation = "investigate" if name and retail_price and retail_price > 0 and not (category_value == "general") else "hold"
    return {
        "product_name": name, "category": category_value, "target_geo": geo,
        "status": "ready_for_dry_run", "demand_signal": {"status": "not_connected", "score": None},
        "competition_signal": {"status": "not_connected", "score": None},
        "supplier_assumption": {"status": "not_validated", "assumed_landed_cost": assumed_landed_cost, "cost_ratio_assumption": 0.35},
        "pricing_signal": {"retail_price": retail_price, "price_band": price_band, "assumed_gross_margin": assumed_margin},
        "risk_flags": risk_flags,
        "recommendation": recommendation,
        "next_actions": next_actions,
        "provenance": {"market_data": "not_connected", "method": "deterministic_input_heuristic"},
        "dry_run": True,
    }
