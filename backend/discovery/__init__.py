"""backend.discovery — product discovery pipeline (Pipeline 1 of the
dropship spine: Discover → Validate → Create → Launch → Optimize).

Aggregates existing signal-engine sources (Amazon bestsellers, Google Trends,
Reddit, TikTok organic) with competitor-ad intelligence into a ranked list of
product opportunities ready for validation.

Public surface:
    discover_products(limit=10) → list of scored opportunity dicts
"""
from __future__ import annotations

import logging
from typing import Any

from backend.discovery.ad_intelligence import competition_summary

_log = logging.getLogger(__name__)


def discover_products(limit: int = 10, min_signal_score: float = 0.5) -> list[dict[str, Any]]:
    """Return ranked product opportunities from all live signal sources.

    Each opportunity combines the raw demand signal with competitor-ad
    intelligence.  The final opportunity score rewards demand and penalizes
    saturated markets:

        opportunity = signal_score * (1 - 0.5 * market_saturation)

    Fail-silent: any source error degrades to the remaining sources; an
    empty signal engine yields its built-in mock signals so the pipeline
    always produces candidates in dev/dry-run.
    """
    from core.signals import signal_engine

    try:
        signals = signal_engine.get()
    except Exception as exc:
        _log.debug("discovery_signals_failed error=%s", exc)
        signals = []

    # Deduplicate by product name, keep the strongest signal per product
    by_product: dict[str, dict] = {}
    for s in signals:
        name = str(s.get("product", "")).strip()
        if not name:
            continue
        score = float(s.get("score", 0.0))
        if score < min_signal_score:
            continue
        prev = by_product.get(name)
        if prev is None or score > prev["signal_score"]:
            by_product[name] = {
                "product": name,
                "signal_score": score,
                "source": s.get("source", "unknown"),
                "platform": s.get("platform", ""),
            }

    opportunities = []
    for name, opp in by_product.items():
        comp = competition_summary(name)
        opp["market_saturation"] = comp["market_saturation"]
        opp["competitor_count"] = comp["competitor_count"]
        opp["competition_difficulty"] = comp["difficulty"]
        opp["opportunity_score"] = round(
            opp["signal_score"] * (1 - 0.5 * comp["market_saturation"]), 4
        )
        opportunities.append(opp)

    opportunities.sort(key=lambda o: -o["opportunity_score"])
    return opportunities[:limit]
