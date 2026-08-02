"""Research-only portfolio and scenario scoring for related products."""
from __future__ import annotations

import hashlib
import random
from typing import Any, Iterable


def _fraction(seed: str) -> float:
    return int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def optimize_top_three(products: Iterable[Any], *, max_products: int = 3) -> dict[str, Any]:
    """Select a related top-three set without creating or launching anything."""
    candidates = list(products)
    if not candidates:
        return {"products": [], "score": 0.0, "method": "research_only"}
    selected = []
    supplier_sets: list[set[str]] = []
    for product in sorted(candidates, key=lambda p: p.score, reverse=True):
        suppliers = {offer.supplier_name for offer in product.supplier_offers}
        if not selected:
            selected.append(product)
            supplier_sets.append(suppliers)
        else:
            overlap = max((len(suppliers & existing) / max(len(suppliers | existing), 1) for existing in supplier_sets), default=0.0)
            if overlap >= 0.2 or product.category == selected[0].category:
                selected.append(product)
                supplier_sets.append(suppliers)
        if len(selected) >= max_products:
            break
    scores = [float(item.score) for item in selected]
    diversity = len({offer.supplier_name for item in selected for offer in item.supplier_offers}) / max(len(selected), 1)
    score = round(sum(scores) / max(len(scores), 1) * 0.75 + min(diversity / 5.0, 1.0) * 0.25, 4)
    return {"products": [item.product_id for item in selected], "score": score,
            "supplier_diversity": round(diversity, 4), "method": "research_only"}


def simulate_product(product: Any, *, samples: int = 300) -> dict[str, Any]:
    """Produce bounded pessimistic/base/optimistic contribution scenarios."""
    margin = dict(product.economics or {})
    revenue = float(margin.get("retail_price", 0.0) or 0.0)
    cost = float(margin.get("landed_cost", 0.0) or 0.0)
    if revenue <= 0:
        revenue = max(cost * 2.0, 1.0)
    base_roas = max(float(product.score) * 3.0, 0.2)
    rng = random.Random(int(_fraction(product.product_id) * 10_000_000))
    values = [max(0.0, base_roas * (0.6 + rng.random() * 0.8)) for _ in range(max(30, samples))]
    values.sort()
    scenarios = {
        "pessimistic": {"roas": round(values[int(len(values) * 0.15)], 4), "margin_per_order": round(revenue - cost * 1.2, 2)},
        "base": {"roas": round(values[int(len(values) * 0.50)], 4), "margin_per_order": round(revenue - cost, 2)},
        "optimistic": {"roas": round(values[int(len(values) * 0.85)], 4), "margin_per_order": round(revenue - cost * 0.9, 2)},
    }
    return {"product_id": product.product_id, "samples": len(values), "scenarios": scenarios,
            "break_even_roas": round(revenue / max(revenue - cost, 0.01), 4)}


def tipping_point(products: Iterable[Any], simulations: Iterable[dict[str, Any]]) -> dict[str, Any]:
    sims = list(simulations)
    if not sims:
        return {"score": 0.0, "status": "insufficient_evidence", "reasons": ["no_simulations"]}
    base = [float(item["scenarios"]["base"]["roas"]) for item in sims]
    pess = [float(item["scenarios"]["pessimistic"]["roas"]) for item in sims]
    positive = sum(value >= 1.0 for value in pess) / len(pess)
    base_positive = sum(value >= 1.0 for value in base) / len(base)
    score = round(0.6 * base_positive + 0.4 * positive, 4)
    return {"score": score, "status": "candidate" if score >= 0.7 else "watch" if score >= 0.5 else "reject",
            "pessimistic_positive_rate": round(positive, 4), "base_positive_rate": round(base_positive, 4),
            "top_three_count": min(len(list(products)), 3)}
