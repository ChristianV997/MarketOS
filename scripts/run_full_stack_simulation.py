#!/usr/bin/env python3
"""Full-stack MarketOS simulation, capital-constrained at 5,000 MXN.

Runs the *actual* production code paths — not a mock model — end to end:

    discover_products()            (backend.discovery)
      -> validate_product()        (backend.validation, real supplier quotes)
      -> build_product()           (backend.creation + backend.commerce:
                                     brand routing, catalog registration)
      -> launch_product()          (backend.launch: TikTok + Meta campaigns)
      -> run_organic_posting()     (backend.organic: Postiz dry-run posts)
      -> ingest_engagement()       (backend.organic: engagement rollup)
      -> simulated customer orders -> signed Stripe webhook
         (api/routes/webhooks.py, exactly like scripts/run_commerce_smoke_test.py)
      -> process_new_orders() / poll_placed_orders()
         (backend.commerce.fulfillment: real supplier order placement)

Every dollar amount produced by discovery/validation/supplier-quoting/launch
is the system's real (deterministic-mock, since no live credentials exist in
this sandbox) output — nothing here is hand-authored fiction. The only
external assumptions this script injects (because no ad platform is
actually connected) are: an FX rate, a campaign duration, and a click/convert
funnel model translating ad spend into a number of orders. Those are called
out explicitly in the report.

Usage:
    python scripts/run_full_stack_simulation.py
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys

sys.path.insert(0, "/home/user/my_OS")

os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_sim_test")

# ── Capital constraint ───────────────────────────────────────────────────────
CAPITAL_MXN = 5000.0
FX_MXN_PER_USD = 18.50          # assumption, stated explicitly in report
CAPITAL_USD = round(CAPITAL_MXN / FX_MXN_PER_USD, 2)

CAMPAIGN_DAYS = 14               # simulation horizon
MAX_PRODUCTS = 3                 # matches run_dropship_cycle(max_products=...) below
AD_RESERVE_FRACTION = 0.80       # 80% of capital risked on ads; 20% opex/buffer
AD_BUDGET_TOTAL_USD = round(CAPITAL_USD * AD_RESERVE_FRACTION, 2)
# run_dropship_cycle's budget_daily is a PER-PRODUCT daily budget (each green
# product gets its own budget_daily * confidence campaign) — divide the total
# reserve across the product slots and the campaign horizon so the sum across
# all launched products cannot exceed what was actually set aside for ads.
AD_BUDGET_DAILY_USD = round(AD_BUDGET_TOTAL_USD / (MAX_PRODUCTS * CAMPAIGN_DAYS), 2)

# Funnel assumptions (explicit, since no live ad account is connected):
ASSUMED_CPC_USD = 0.35           # blended TikTok+Meta CPC, low-competition dropship niches
BASE_CVR = 0.02                 # 2% baseline landing-page conversion rate
CVR_CONFIDENCE_SCALER = 0.05     # validation confidence adds up to +5pp CVR at confidence=1.0
STRIPE_PCT_FEE = 0.029
STRIPE_FIXED_FEE_USD = 0.30
HOSTING_OPEX_USD_PER_MONTH = 12.0   # Postiz + small VPS self-host, amortized


def _stripe_signature(body: bytes, secret: str) -> str:
    import time
    ts = int(time.time())
    signed_payload = f"{ts}.".encode() + body
    sig = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def _fire_checkout_webhook(client, order_id: str, brand_id: str, product_id: str,
                           amount_usd: float, email: str, name: str, city: str) -> bool:
    event = {
        "id": f"evt_{order_id}",
        "object": "event",
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": order_id,
            "amount_total": int(round(amount_usd * 100)),
            "currency": "usd",
            "metadata": {"brand_id": brand_id, "product_id": product_id, "qty": "1",
                        "utm_source": "tiktok", "utm_campaign": "sim"},
            "customer_details": {"email": email, "name": name},
            "shipping_details": {"address": {
                "line1": "1 Simulation Ave", "city": city, "state": "TX",
                "postal_code": "78701", "country": "US",
            }},
        }},
    }
    body = json.dumps(event).encode()
    sig = _stripe_signature(body, os.environ["STRIPE_WEBHOOK_SECRET"])
    resp = client.post("/webhooks/stripe", content=body, headers={"Stripe-Signature": sig})
    return resp.status_code == 200 and resp.json().get("status") == "ok"


def main() -> int:
    report: dict = {"capital": {}, "products": [], "orders": [], "financials": {}}

    print("\nMarketOS Full-Stack Simulation — 5,000 MXN Capital")
    print("=" * 72)
    print(f"FX assumption: {FX_MXN_PER_USD} MXN/USD -> capital = ${CAPITAL_USD} USD")
    print(f"Ad budget reserved: {int(AD_RESERVE_FRACTION*100)}% = ${AD_BUDGET_TOTAL_USD} USD "
         f"over {CAMPAIGN_DAYS} days = ${AD_BUDGET_DAILY_USD}/day")
    print("=" * 72)

    report["capital"] = {
        "capital_mxn": CAPITAL_MXN, "fx_mxn_per_usd": FX_MXN_PER_USD,
        "capital_usd": CAPITAL_USD, "ad_budget_total_usd": AD_BUDGET_TOTAL_USD,
        "ad_budget_daily_usd": AD_BUDGET_DAILY_USD, "campaign_days": CAMPAIGN_DAYS,
    }

    # ── Stage 1-4: discover -> validate -> build (brand/catalog) -> launch ──
    from backend.dropship import run_dropship_cycle

    cycle = run_dropship_cycle(max_products=MAX_PRODUCTS, budget_daily=AD_BUDGET_DAILY_USD,
                               platforms=("tiktok", "meta"))
    print(f"\n[1-4] Dropship cycle: status={cycle['status']} "
         f"discovered={cycle.get('discovered', 0)} validated={cycle.get('validated', 0)} "
         f"green={cycle.get('green', 0)} launched={cycle.get('launched', 0)}")

    launches = cycle.get("launches", [])
    if not launches:
        print("No products cleared validation — nothing to simulate downstream. Exiting.")
        report["financials"] = {"status": "no_launches"}
        _print_and_save(report)
        return 1

    from backend.commerce.catalog import product_catalog, product_slug
    from backend.commerce.brands import brand_registry
    from backend.validation.suppliers import find_best_supplier

    for launch in launches:
        product = launch["product"]
        brand_id = launch.get("brand_id", "")
        brand = brand_registry.get(brand_id)
        # LandingStorefront derives the catalog product_id from the full
        # *generated listing title* (e.g. "Wireless Earbuds Pro — Premium
        # Quality, Fast Shipping"), not the raw discovery product name — the
        # slug is the last path segment of the page URL launch() returned.
        page_url = launch.get("page_url", "")
        catalog_product_id = page_url.rstrip("/").rsplit("/", 1)[-1] if page_url else product_slug(product)
        entry = product_catalog.get(catalog_product_id)
        quote = find_best_supplier(product, category=(brand.category if brand else "general"))

        row = {
            "product": product,
            "catalog_product_id": catalog_product_id,
            "brand_id": brand_id,
            "brand_name": brand.name if brand else "",
            "category": brand.category if brand else "",
            "confidence": launch.get("confidence"),
            "retail_price_usd": launch.get("retail_price"),
            "supplier": quote.supplier if quote else (entry.supplier if entry else ""),
            "landed_cost_usd": quote.landed_cost if quote else (entry.landed_cost if entry else 0.0),
            "supplier_reliability": quote.reliability if quote else None,
            "fulfillment_days": quote.fulfillment_days if quote else None,
            "page_url": launch.get("page_url", ""),
            "ad_budget_daily_usd": launch.get("budget"),
            "campaigns": launch.get("campaigns", []),
            "catalog_status": entry.status if entry else "",
        }
        report["products"].append(row)
        print(f"    - {product} | brand={row['brand_name']} ({row['category']}) | "
             f"supplier={row['supplier']} landed=${row['landed_cost_usd']} | "
             f"retail=${row['retail_price_usd']} | confidence={row['confidence']}")

    # ── Stage 5: organic posting + engagement ingestion ─────────────────────
    from backend.organic.poster import run_organic_posting
    from backend.organic.engagement import ingest_engagement, product_engagement

    organic_result = run_organic_posting()
    engagement_result = ingest_engagement()
    print(f"\n[5] Organic posting: {organic_result.get('status', organic_result)} | "
         f"engagement ingestion: {engagement_result.get('status', engagement_result)}")
    for row in report["products"]:
        entry = product_catalog.get(row["catalog_product_id"])
        listing_title = entry.title if entry else row["product"]
        eng = product_engagement(listing_title)
        row["organic_engagement_rate"] = eng.get("mean_engagement_rate", 0.0)
        row["organic_posts"] = eng.get("posts", 0)
        row["organic_impressions"] = eng.get("impressions", 0)
        print(f"    - {row['product']}: posts={row['organic_posts']} "
             f"impressions={row['organic_impressions']} "
             f"engagement_rate={row['organic_engagement_rate']}")

    # ── Stage 6: funnel model -> simulated orders -> real webhook path ───────
    from fastapi.testclient import TestClient
    from backend.api import app

    client = TestClient(app)
    total_orders = 0
    order_seq = 0
    customer_cities = ["Austin", "Dallas", "Houston", "Phoenix", "Denver", "Miami"]

    for row in report["products"]:
        daily_budget = row["ad_budget_daily_usd"] or 0.0
        total_ad_spend = round(daily_budget * CAMPAIGN_DAYS, 2)
        clicks = total_ad_spend / ASSUMED_CPC_USD if ASSUMED_CPC_USD else 0.0
        confidence = row["confidence"] or 0.0
        eng = row["organic_engagement_rate"] or 0.0
        cvr = BASE_CVR + CVR_CONFIDENCE_SCALER * confidence + 0.5 * eng
        expected_orders = int(round(clicks * cvr))
        row["total_ad_spend_usd"] = total_ad_spend
        row["estimated_clicks"] = round(clicks, 1)
        row["modeled_cvr"] = round(cvr, 4)
        row["expected_orders"] = expected_orders

        placed = 0
        for i in range(expected_orders):
            order_seq += 1
            order_id = f"sim_order_{order_seq}"
            city = customer_cities[order_seq % len(customer_cities)]
            ok = _fire_checkout_webhook(
                client, order_id, row["brand_id"], row["catalog_product_id"],
                row["retail_price_usd"] or 0.0,
                email=f"customer{order_seq}@sim.marketos.test",
                name=f"Sim Customer {order_seq}", city=city,
            )
            if ok:
                placed += 1
        row["orders_recorded"] = placed
        total_orders += placed
        print(f"    - {row['product']}: ad_spend=${total_ad_spend} clicks~{row['estimated_clicks']} "
             f"cvr={row['modeled_cvr']} -> {placed} simulated orders")

    print(f"\n[6] Total simulated orders across all products: {total_orders}")

    # ── Stage 7: fulfillment — route + place with suppliers, poll to terminal ─
    from backend.commerce.fulfillment import process_new_orders, poll_placed_orders

    ff_result = process_new_orders(limit=1000)
    print(f"[7] process_new_orders: {ff_result}")
    for _ in range(5):
        poll_result = poll_placed_orders(limit=1000)
        if poll_result.get("status") == "skipped":
            break
        print(f"    poll_placed_orders: {poll_result}")

    # ── Stage 8: financial rollup from the real order repository ────────────
    from backend.data.repositories.order_repository import order_repository

    all_orders = []
    for status in ["RECEIVED", "PLACED", "SHIPPED", "DELIVERED", "FAILED", "REFUNDED"]:
        all_orders.extend(order_repository.orders_by_status(status, limit=1000))

    revenue_usd = 0.0
    cogs_usd = 0.0
    stripe_fees_usd = 0.0
    status_counts: dict[str, int] = {}
    entry_by_product = {r["catalog_product_id"]: r for r in report["products"]}

    for o in all_orders:
        status_counts[o.fulfillment_status] = status_counts.get(o.fulfillment_status, 0) + 1
        if o.fulfillment_status in ("FAILED",):
            continue  # payment never actually settles for a failed order in this model
        revenue_usd += o.amount * o.qty
        stripe_fees_usd += o.amount * o.qty * STRIPE_PCT_FEE + STRIPE_FIXED_FEE_USD
        row = entry_by_product.get(o.product_id)
        if row:
            cogs_usd += row["landed_cost_usd"] * o.qty

    total_ad_spend_usd = sum(r["total_ad_spend_usd"] for r in report["products"])
    hosting_opex_usd = round(HOSTING_OPEX_USD_PER_MONTH * (CAMPAIGN_DAYS / 30.0), 2)
    total_opex_usd = round(stripe_fees_usd + hosting_opex_usd, 2)

    net_profit_usd = round(revenue_usd - cogs_usd - total_ad_spend_usd - total_opex_usd, 2)
    net_profit_mxn = round(net_profit_usd * FX_MXN_PER_USD, 2)
    ending_capital_mxn = round(CAPITAL_MXN + net_profit_mxn, 2)

    financials = {
        "orders_total": len(all_orders),
        "order_status_breakdown": status_counts,
        "revenue_usd": round(revenue_usd, 2),
        "revenue_mxn": round(revenue_usd * FX_MXN_PER_USD, 2),
        "cogs_usd": round(cogs_usd, 2),
        "cogs_mxn": round(cogs_usd * FX_MXN_PER_USD, 2),
        "ad_spend_usd": round(total_ad_spend_usd, 2),
        "ad_spend_mxn": round(total_ad_spend_usd * FX_MXN_PER_USD, 2),
        "stripe_fees_usd": round(stripe_fees_usd, 2),
        "hosting_opex_usd": hosting_opex_usd,
        "total_opex_usd": total_opex_usd,
        "total_opex_mxn": round(total_opex_usd * FX_MXN_PER_USD, 2),
        "net_profit_usd": net_profit_usd,
        "net_profit_mxn": net_profit_mxn,
        "starting_capital_mxn": CAPITAL_MXN,
        "ending_capital_mxn": ending_capital_mxn,
        "roi_pct": round(net_profit_mxn / CAPITAL_MXN * 100, 1),
    }
    report["financials"] = financials

    print("\n" + "=" * 72)
    print("FINANCIAL SUMMARY (over {} simulated days)".format(CAMPAIGN_DAYS))
    print("=" * 72)
    for k, v in financials.items():
        print(f"  {k}: {v}")
    print("=" * 72)

    _print_and_save(report)
    return 0


def _print_and_save(report: dict) -> None:
    out_path = "/tmp/claude-0/-home-user-my-OS/ddae6c32-c7b9-5228-a23b-19efc6d1c0dd/scratchpad/simulation_report.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nFull machine-readable report saved to: {out_path}")


if __name__ == "__main__":
    sys.exit(main())
