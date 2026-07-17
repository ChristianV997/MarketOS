"""backend.metrics.profitability — actual profit attribution + accuracy.

Joins three sources per product:
  1. the launch snapshot (state/dropship.json — predicted ROAS, confidence,
     budget, campaign IDs)
  2. the campaign metric log (state/campaign_metrics.jsonl — real spend,
     revenue)
  3. the retail price / margin verdict captured at validation time

to answer the two questions that matter:
  * how much money did each product actually make?
  * how wrong were our predictions (so the next cycle can be less wrong)?
"""
from __future__ import annotations

import logging
import time
from typing import Any

from backend.core.persistence import load_json, state_path

_log = logging.getLogger(__name__)

_DROPSHIP_SNAPSHOT = state_path("dropship.json")


def _launched_products() -> dict[str, dict]:
    """product → {predicted_roas, confidence, retail_price, budget, campaign_ids}"""
    snapshot = load_json(_DROPSHIP_SNAPSHOT, default={}) or {}
    out: dict[str, dict] = {}
    for launch in snapshot.get("launches", []):
        product = launch.get("product", "")
        if not product:
            continue
        out[product] = {
            "predicted_roas": float(launch.get("predicted_roas", 1.0)),
            "confidence": float(launch.get("confidence", 0.5)),
            "retail_price": launch.get("retail_price"),
            "budget": float(launch.get("budget", 0.0)),
            "campaign_ids": [c.get("campaign_id", "")
                             for c in launch.get("campaigns", [])
                             if c.get("campaign_id")],
        }
    return out


def calculate_profitability(lookback_days: int = 7) -> dict[str, Any]:
    """Actual profitability per product + overall prediction accuracy.

    Products with no observed spend yet are listed under ``awaiting_data``
    rather than silently dropped — "no data" and "no profit" are different
    answers.
    """
    from backend.metrics.campaign_metrics import campaign_performance

    launched = _launched_products()
    perf = campaign_performance(lookback_days=lookback_days)

    # campaign_id → (spend, revenue); campaign→product resolves via launch
    # snapshot first, falling back to the metric log's own attribution.
    by_campaign = {c["campaign_id"]: c for c in perf}

    products: list[dict] = []
    awaiting: list[str] = []
    total_spend = total_revenue = 0.0
    roas_errors: list[float] = []

    for product, launch in launched.items():
        spend = revenue = 0.0
        for cid in launch["campaign_ids"]:
            c = by_campaign.get(cid)
            if c:
                spend += c["spend"]
                revenue += c["revenue"]
        # metric rows attributed by product name but launched under an
        # unknown/rotated campaign id still count
        for c in perf:
            if c["product"] == product and c["campaign_id"] not in launch["campaign_ids"]:
                spend += c["spend"]
                revenue += c["revenue"]

        if spend <= 0:
            awaiting.append(product)
            continue

        actual_roas = revenue / spend
        predicted = launch["predicted_roas"]
        roas_error_pct = ((actual_roas - predicted) / predicted * 100) if predicted > 0 else 0.0
        profit = revenue - spend

        products.append({
            "product": product,
            "confidence": round(launch["confidence"], 2),
            "spend": round(spend, 2),
            "revenue": round(revenue, 2),
            "actual_profit": round(profit, 2),
            "actual_roas": round(actual_roas, 2),
            "actual_roi_pct": round(profit / spend * 100, 1),
            "predicted_roas": round(predicted, 2),
            "roas_error_pct": round(roas_error_pct, 1),
            "status": "profitable" if profit > 0 else "loss",
        })
        total_spend += spend
        total_revenue += revenue
        roas_errors.append(roas_error_pct)

    total_profit = total_revenue - total_spend
    avg_error = sum(roas_errors) / len(roas_errors) if roas_errors else 0.0

    return {
        "status": "ok",
        "period_days": lookback_days,
        "generated_at": time.time(),
        "total_spend": round(total_spend, 2),
        "total_revenue": round(total_revenue, 2),
        "total_profit": round(total_profit, 2),
        "roi_pct": round(total_profit / total_spend * 100, 1) if total_spend > 0 else 0.0,
        "avg_roas": round(total_revenue / total_spend, 2) if total_spend > 0 else 0.0,
        "num_products": len(products),
        "profitable_count": sum(1 for p in products if p["status"] == "profitable"),
        "products": sorted(products, key=lambda p: p["actual_profit"], reverse=True),
        "awaiting_data": awaiting,
        "accuracy": {
            "avg_roas_error_pct": round(avg_error, 1),
            "bias": ("optimistic" if avg_error < 0 else
                     "pessimistic" if avg_error > 0 else "neutral"),
            "samples": len(roas_errors),
        },
    }


def revenue_forecast(horizon_days: int = 7) -> dict[str, Any]:
    """Project revenue from currently-launched campaigns.

    Bands:
      pessimistic — every campaign only ever hits ROAS 1.0 (breakeven ads)
      realistic   — each campaign hits its predicted ROAS
      optimistic  — predicted ROAS +50%

    When real outcomes exist, the realistic band is corrected by the
    observed average prediction error, so the forecast improves as data
    accumulates.
    """
    launched = _launched_products()
    if not launched:
        return {"status": "no_campaigns", "horizon_days": horizon_days,
                "campaigns_live": 0, "spend_projected": 0.0,
                "revenue_pessimistic": 0.0, "revenue_realistic": 0.0,
                "revenue_optimistic": 0.0, "error_correction_pct": 0.0}

    # Observed prediction error → correction factor for the realistic band
    report = calculate_profitability(lookback_days=30)
    err_pct = report["accuracy"]["avg_roas_error_pct"] if report["accuracy"]["samples"] else 0.0
    correction = 1.0 + err_pct / 100.0

    daily_spend = sum(l["budget"] for l in launched.values())
    spend = daily_spend * horizon_days
    realistic_roas = [l["predicted_roas"] * correction for l in launched.values()]
    weighted = (
        sum(l["budget"] * r for l, r in zip(launched.values(), realistic_roas))
        / daily_spend if daily_spend > 0 else 1.0
    )

    return {
        "status": "ok",
        "horizon_days": horizon_days,
        "campaigns_live": sum(len(l["campaign_ids"]) for l in launched.values()),
        "products_live": len(launched),
        "spend_projected": round(spend, 2),
        "revenue_pessimistic": round(spend * 1.0, 2),
        "revenue_realistic": round(spend * weighted, 2),
        "revenue_optimistic": round(spend * weighted * 1.5, 2),
        "profit_realistic": round(spend * (weighted - 1.0), 2),
        "blended_roas": round(weighted, 2),
        "error_correction_pct": round(err_pct, 1),
    }


def product_timeline(product: str, lookback_days: int = 30) -> list[dict]:
    """Per-observation spend/revenue/ROAS for one product, oldest first."""
    from backend.metrics.campaign_metrics import _read_rows

    since = time.time() - lookback_days * 86400
    rows = [r for r in _read_rows(since) if r.get("product") == product]
    rows.sort(key=lambda r: r["timestamp"])
    out = []
    for r in rows:
        spend = r.get("spend_usd", 0.0)
        revenue = r.get("revenue_usd", 0.0)
        out.append({
            "timestamp": r["timestamp"],
            "campaign_id": r.get("campaign_id", ""),
            "platform": r.get("platform", ""),
            "spend": round(spend, 2),
            "revenue": round(revenue, 2),
            "profit": round(revenue - spend, 2),
            "roas": round(revenue / spend, 2) if spend > 0 else 0.0,
        })
    return out


__all__ = ["calculate_profitability", "revenue_forecast", "product_timeline"]
