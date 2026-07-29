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

Revenue reconciliation
-----------------------
Per-campaign revenue in the metric log is each ad platform's own
self-reported figure (``est_spend * platform_roas`` — see
``orchestrator/main.py``), and platforms' attribution windows overlap
(a sale both Meta and TikTok separately claim credit for). Shopify orders
carry no campaign/product tag in this codebase, so a true order-level
join isn't available — instead ``backend.metrics.attribution`` applies
revenue reconciliation: total platform-claimed revenue across the whole
portfolio is scaled down to Shopify's independently-reported total for
the same window whenever the platforms' claims exceed it, and every
campaign's share is reduced proportionally. Both the raw (pre-reconciliation)
and reconciled totals are always returned, and which one the ``products``
list's ``revenue``/``actual_roas`` fields reflect is controlled by
``ATTRIBUTION_RECONCILE_LIVE`` (default: false — reconciled figures are
computed and exposed for comparison, but don't yet drive other logic,
per the shadow-mode rollout requirement).
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

from backend.core.persistence import load_json, state_path

_log = logging.getLogger(__name__)

_DROPSHIP_SNAPSHOT = state_path("dropship.json")


def _reconcile_live() -> bool:
    return os.getenv("ATTRIBUTION_RECONCILE_LIVE", "false").lower() == "true"


def _shopify_ground_truth(lookback_days: int) -> float | None:
    """Independent (non-ad-platform) revenue ground truth for the window.

    None means unavailable (e.g., Shopify not configured / no orders) —
    reconciliation is skipped rather than guessed in that case.
    """
    try:
        from backend.integrations.shopify_client import get_orders, compute_metrics
        orders = get_orders(last_n_minutes=lookback_days * 24 * 60)
        metrics = compute_metrics(orders)
        revenue = float(metrics.get("revenue", 0.0))
        return revenue if revenue > 0 else None
    except Exception as exc:
        _log.debug("shopify_ground_truth_unavailable error=%s", exc)
        return None


def _stripe_ground_truth(lookback_days: int) -> float | None:
    """Independent (non-ad-platform) revenue ground truth for the window.

    A second, additive revenue channel alongside Shopify (e.g. products sold
    via a direct checkout rather than the Shopify storefront). None means
    unavailable (Stripe not configured / no charges).

    Checked explicitly rather than trusting get_revenue()'s return value:
    that connector always falls back to nonzero mock charges even when
    STRIPE_SECRET_KEY is unset (by design, for callers that just want "some
    usable figure"), which would otherwise silently inject a phantom mock
    revenue into every reconciliation regardless of whether Stripe is
    actually configured.
    """
    if not os.getenv("STRIPE_SECRET_KEY"):
        return None
    try:
        from connectors.stripe_connector import get_revenue
        result = get_revenue(last_n_minutes=lookback_days * 24 * 60)
        if result.get("source") != "live":
            # Configured but the API call itself failed (network error,
            # rotated/invalid key, Stripe outage) — get_revenue() falls back
            # to nonzero mock charges in that case, which would otherwise
            # silently inject phantom revenue into reconciliation with no
            # indication anything went wrong.
            _log.warning("stripe_ground_truth_degraded source=%s", result.get("source"))
            return None
        revenue = float(result.get("total_revenue", 0.0))
        return revenue if revenue > 0 else None
    except Exception as exc:
        _log.debug("stripe_ground_truth_unavailable error=%s", exc)
        return None


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
    from backend.metrics.attribution import reconcile_revenue

    launched = _launched_products()
    perf = campaign_performance(lookback_days=lookback_days)

    # campaign_id → (spend, revenue); campaign→product resolves via launch
    # snapshot first, falling back to the metric log's own attribution.
    by_campaign = {c["campaign_id"]: c for c in perf}

    # Revenue reconciliation (Phase 1 of the ROI overhaul): Shopify orders
    # carry no per-product/campaign tag, so ground truth is only available
    # at the portfolio level — reconcile total platform-claimed revenue
    # against it, then use each campaign's *reconciled* share below.
    raw_campaign_revenue = {c["campaign_id"]: c["revenue"] for c in perf}
    shopify_gt = _shopify_ground_truth(lookback_days)
    stripe_gt = _stripe_ground_truth(lookback_days)
    # Shopify orders and Stripe charges are additive, non-overlapping revenue
    # channels — sum whichever are available; None only when *neither* has data,
    # preserving the existing "skip reconciliation" contract for that case.
    ground_truth = (
        (shopify_gt or 0.0) + (stripe_gt or 0.0)
        if (shopify_gt is not None or stripe_gt is not None) else None
    )
    reconciliation = reconcile_revenue(raw_campaign_revenue, ground_truth)
    reconciled_by_campaign = reconciliation.per_campaign_revenue
    use_reconciled = _reconcile_live()

    def _reconciled_revenue_for(cid: str, raw: float) -> float:
        """Always the reconciled figure, for shadow-mode comparison —
        independent of whether it's live-driving `revenue`/`actual_roas`."""
        return reconciled_by_campaign.get(cid, raw)

    products: list[dict] = []
    awaiting: list[str] = []
    total_spend = total_revenue_raw = total_revenue_reconciled = 0.0
    roas_errors: list[float] = []

    for product, launch in launched.items():
        spend = revenue_raw = revenue_reconciled = 0.0
        seen_cids: set[str] = set()
        for cid in launch["campaign_ids"]:
            c = by_campaign.get(cid)
            if c:
                spend += c["spend"]
                revenue_raw += c["revenue"]
                revenue_reconciled += _reconciled_revenue_for(cid, c["revenue"])
                seen_cids.add(cid)
        # metric rows attributed by product name but launched under an
        # unknown/rotated campaign id still count
        for c in perf:
            if c["product"] == product and c["campaign_id"] not in seen_cids:
                spend += c["spend"]
                revenue_raw += c["revenue"]
                revenue_reconciled += _reconciled_revenue_for(c["campaign_id"], c["revenue"])

        if spend <= 0:
            awaiting.append(product)
            continue

        revenue = revenue_reconciled if use_reconciled else revenue_raw
        actual_roas = revenue / spend
        predicted = launch["predicted_roas"]
        roas_error_pct = ((actual_roas - predicted) / predicted * 100) if predicted > 0 else 0.0
        profit = revenue - spend

        products.append({
            "product": product,
            "confidence": round(launch["confidence"], 2),
            "spend": round(spend, 2),
            "revenue": round(revenue, 2),
            "revenue_raw": round(revenue_raw, 2),
            "revenue_reconciled": round(revenue_reconciled, 2),
            "actual_profit": round(profit, 2),
            "actual_roas": round(actual_roas, 2),
            "actual_roi_pct": round(profit / spend * 100, 1),
            "predicted_roas": round(predicted, 2),
            "roas_error_pct": round(roas_error_pct, 1),
            "status": "profitable" if profit > 0 else "loss",
        })
        total_spend += spend
        total_revenue_raw += revenue_raw
        total_revenue_reconciled += revenue_reconciled
        roas_errors.append(roas_error_pct)

    total_revenue = total_revenue_reconciled if use_reconciled else total_revenue_raw
    total_profit = total_revenue - total_spend
    avg_error = sum(roas_errors) / len(roas_errors) if roas_errors else 0.0

    return {
        "status": "ok",
        "period_days": lookback_days,
        "generated_at": time.time(),
        "total_spend": round(total_spend, 2),
        "total_revenue": round(total_revenue, 2),
        "total_revenue_raw": round(total_revenue_raw, 2),
        "total_revenue_reconciled": round(total_revenue_reconciled, 2),
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
        "attribution_reconciliation": reconciliation.to_dict() | {
            "live": use_reconciled,
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
