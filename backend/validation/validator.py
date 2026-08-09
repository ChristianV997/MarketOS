"""backend.validation.validator — the go/no-go gate for product candidates.

Combines the three validation dimensions into one confidence score:

    margin health      40%   (net margin verdict from unit economics)
    market openness    35%   (1 - saturation from competitor-ad intel)
    supplier quality   25%   (reliability of the best available quote)

A product is ready for creation at confidence >= 0.60 ("green"); 0.45–0.60
reads "yellow" (park it, revisit when competition or costs move); below 0.45
is "red" (skip).  Thresholds are env-tunable.

Every validated product is also indexed into backend.vector's PRODUCTS
collection (name + confidence + recommendation + category), and each new
candidate first queries that collection for past semantically-similar
products — this is the "similar past winners/losers" read path the vector
cognition fabric (backend/vector/semantic_search.py) was built for but,
until now, nothing ever called. A cluster of highly-similar past "red"
verdicts surfaces as a risk flag; it never changes the numeric confidence
score itself, since the 3-dimension weighting above is well-established and
a 4th silently-blended dimension would change historical scoring behavior.
Best-effort: any vector-store failure (offline, Qdrant unreachable) is
caught and logged, never blocks validation.
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

# Similar past products at/above this cosine score count as a real match
# for the "repeated failure" risk flag below.
_SIMILARITY_MATCH_THRESHOLD = float(os.getenv("VALIDATE_SIMILARITY_THRESHOLD", "0.75"))


def _find_similar_past_products(product_name: str, top_k: int = 3) -> list[dict[str, Any]]:
    """Query backend.vector's PRODUCTS collection for past validated products
    semantically similar to *product_name*. Returns [] on any failure
    (offline, empty store, vector stack unavailable) — never raises.
    """
    try:
        from backend.vector.semantic_search import find_similar_products
        hits = find_similar_products(product_name, top_k=top_k, threshold=_SIMILARITY_MATCH_THRESHOLD)
        return [
            {
                "product": h.payload.get("name", ""),
                "similarity": round(h.score, 4),
                "confidence": h.payload.get("confidence"),
                "recommendation": h.payload.get("recommendation"),
            }
            for h in hits
        ]
    except Exception as exc:
        _log.debug("vector_similar_products_lookup_failed error=%s", exc)
        return []


def _index_validated_product(product_name: str, verdict: dict[str, Any], category: str) -> None:
    """Upsert *product_name* + its verdict into the PRODUCTS collection so
    future validate_product() calls can find it as a "past similar product".
    Best-effort: failures are logged, never raised.
    """
    try:
        from backend.vector.embeddings import embed_text
        from backend.vector.indexing import product_record, index_batch
        record = product_record(
            product_name,
            embed_text(product_name),
            confidence=verdict["confidence"],
            recommendation=verdict["recommendation"],
            category=category,
        )
        index_batch([record])
    except Exception as exc:
        _log.debug("vector_product_index_failed error=%s", exc)


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
        verdict = {
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
        _index_validated_product(product_name, verdict, category)
        return verdict

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

    similar_past_products = _find_similar_past_products(product_name)
    similar_red_count = sum(
        1 for p in similar_past_products if p.get("recommendation") == "red"
    )
    if similar_red_count >= 2:
        risk_flags.append("similar_to_repeated_past_failures")

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
        "similar_past_products": similar_past_products,
    }
    _log.info("product_validated product=%s confidence=%s recommendation=%s",
              product_name, confidence, recommendation)
    _index_validated_product(product_name, verdict, category)
    return verdict
