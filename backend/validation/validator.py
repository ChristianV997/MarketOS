"""backend.validation.validator — the go/no-go gate for product candidates.

Combines the three validation dimensions into one confidence score:

    margin health      40%   (net margin verdict from unit economics)
    market openness    35%   (1 - saturation from competitor-ad intel)
    supplier quality   25%   (reliability of the best available quote)

A product is ready for creation at confidence >= 0.60 ("green"); 0.45–0.60
reads "yellow" (park it, revisit when competition or costs move); below 0.45
is "red" (skip).  Thresholds are env-tunable.
"""
from __future__ import annotations

import logging
from typing import Any

from backend.discovery.ad_intelligence import competition_summary
from backend.validation.margin_calculator import calculate_margin, suggest_retail_price
from backend.validation.suppliers import find_best_supplier, SupplierQuote

import os

_log = logging.getLogger(__name__)

_GREEN_THRESHOLD  = float(os.getenv("VALIDATE_GREEN_THRESHOLD", "0.60"))
_YELLOW_THRESHOLD = float(os.getenv("VALIDATE_YELLOW_THRESHOLD", "0.45"))

_W_MARGIN, _W_MARKET, _W_SUPPLIER = 0.40, 0.35, 0.25

_MARGIN_SCORES = {"profitable": 1.0, "breakeven": 0.5, "loss": 0.0}


def validate_product(
    product_name: str,
    retail_price: float | None = None,
    supplier_quote: SupplierQuote | None = None,
    category: str = "general",
) -> dict[str, Any]:
    """Validate one product candidate end to end.

    When retail_price is omitted, prices at the level needed for a 20% net
    margin (bisection over the margin model) — the returned suggested_price
    is what the store should charge.

    ``category`` (Phase 6, default "general") threads through to
    ``find_best_supplier`` (category-aware return-risk supplier ranking)
    and ``calculate_margin`` (category-aware return rate); omitting it
    preserves exact pre-Phase-6 behavior.

    Never raises; a product with no supplier at all comes back "red" with a
    no_supplier flag rather than an exception.
    """
    quote = supplier_quote or find_best_supplier(product_name, category=category)
    if quote is None:
        return {
            "product": product_name,
            "confidence": 0.0,
            "recommendation": "red",
            "ready_for_creation": False,
            "risk_flags": ["no_supplier"],
            "margin": None,
            "competition": None,
            "supplier": None,
            "suggested_price": None,
        }

    suggested = suggest_retail_price(quote.landed_cost, target_net_margin_pct=20.0)
    price = retail_price if retail_price and retail_price > 0 else suggested

    margin = calculate_margin(
        supplier_cost=quote.cost,
        retail_price=price,
        shipping_cost=quote.shipping,
        category=category,
    )
    competition = competition_summary(product_name)

    margin_score   = _MARGIN_SCORES.get(margin["margin_status"], 0.0)
    market_score   = 1.0 - competition["market_saturation"]
    supplier_score = quote.reliability

    confidence = round(
        _W_MARGIN * margin_score
        + _W_MARKET * market_score
        + _W_SUPPLIER * supplier_score,
        4,
    )

    risk_flags = []
    if margin["margin_status"] == "loss":
        risk_flags.append("negative_margin")
    if competition["market_saturation"] > 0.8:
        risk_flags.append("saturated_market")
    if quote.reliability < 0.75:
        risk_flags.append("weak_supplier")
    if quote.fulfillment_days > 14:
        risk_flags.append("slow_fulfillment")

    if confidence >= _GREEN_THRESHOLD and not risk_flags:
        recommendation = "green"
    elif confidence >= _YELLOW_THRESHOLD:
        recommendation = "yellow"
    else:
        recommendation = "red"

    verdict = {
        "product": product_name,
        "confidence": confidence,
        "recommendation": recommendation,
        "ready_for_creation": recommendation == "green",
        "risk_flags": risk_flags,
        "margin": margin,
        "competition": competition,
        "supplier": quote.to_dict(),
        "suggested_price": suggested,
        "retail_price": round(price, 2),
    }
    _log.info("product_validated product=%s confidence=%s recommendation=%s",
              product_name, confidence, recommendation)
    return verdict
