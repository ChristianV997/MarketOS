#!/usr/bin/env python3
"""Commerce closed-loop smoke test — "does the money path actually work?"

Runs the full customer journey end to end, entirely offline (no network,
no credentials): create brands -> route validated products into their
catalogs -> render landing pages -> simulate a signed Stripe
checkout.session.completed webhook -> assert the order + customer landed
in the system of record -> forward the order to its supplier -> assert
the fulfillment state machine advances -> assert LTV + ROAS attribution
were fed automatically.

Usage:
    python scripts/run_commerce_smoke_test.py
"""
import hashlib
import hmac
import json
import os
import sys
import time

sys.path.insert(0, "/home/user/my_OS")

os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_smoke_test")


def _stripe_signature(body: bytes, secret: str) -> str:
    ts = int(time.time())
    signed_payload = f"{ts}.".encode() + body
    sig = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def main() -> int:
    from fastapi.testclient import TestClient

    from backend.commerce.brands import Brand, brand_registry
    from backend.commerce.catalog import STATUS_LIVE, CatalogEntry, product_catalog

    print("\nMarketOS Commerce Closed-Loop Smoke Test")
    print("=" * 60)

    # 1. Create two brands, three catalog products
    beauty = Brand(brand_id="beauty", name="Beauty Collective", category="beauty")
    home = Brand(brand_id="home-goods", name="Home Goods Co", category="home")
    brand_registry.upsert(beauty)
    brand_registry.upsert(home)
    print(f"[1] Brands created: {beauty.brand_id}, {home.brand_id}")

    products = [
        CatalogEntry(product_id="jade-roller", brand_id="beauty", title="Jade Roller",
                    retail_price=19.99, supplier="cj_dropshipping",
                    supplier_product_id="cj_sku_1", landed_cost=6.0,
                    status=STATUS_LIVE, description_html="<p>Cooling relief.</p>",
                    bullets=["Natural jade", "Reduces puffiness"]),
        CatalogEntry(product_id="led-lights", brand_id="home-goods", title="LED Strip Lights",
                    retail_price=13.85, supplier="spocket",
                    supplier_product_id="sp_sku_2", landed_cost=4.5,
                    status=STATUS_LIVE),
        CatalogEntry(product_id="resistance-bands", brand_id="home-goods",
                    title="Resistance Bands Set", retail_price=24.99, supplier="zendrop",
                    supplier_product_id="zd_sku_3", landed_cost=8.0,
                    status=STATUS_LIVE),
    ]
    for p in products:
        product_catalog.register(p)
    print(f"[2] Routed {len(products)} validated products into catalogs")

    # 3. Render landing pages via TestClient
    from backend.api import app
    client = TestClient(app)
    ok_pages = 0
    for p in products:
        resp = client.get(f"/s/{p.brand_id}/{p.product_id}?utm_source=tiktok&utm_campaign=smoke")
        if resp.status_code == 200 and p.title in resp.text:
            ok_pages += 1
    print(f"[3] Landing pages rendered: {ok_pages}/{len(products)} OK")

    # 4. Simulate a signed Stripe checkout.session.completed webhook
    event = {
        "id": "evt_smoke_1",
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": "cs_smoke_1",
            "amount_total": 1999,
            "currency": "usd",
            "metadata": {"brand_id": "beauty", "product_id": "jade-roller",
                        "qty": "1", "utm_source": "tiktok", "utm_campaign": "smoke"},
            "customer_details": {"email": "smoke@example.com", "name": "Smoke Tester"},
            "shipping_details": {"address": {
                "line1": "123 Main St", "city": "Austin", "state": "TX",
                "postal_code": "78701", "country": "US",
            }},
        }},
    }
    body = json.dumps(event).encode()
    sig = _stripe_signature(body, os.environ["STRIPE_WEBHOOK_SECRET"])
    resp = client.post("/webhooks/stripe", content=body, headers={"Stripe-Signature": sig})
    webhook_ok = resp.status_code == 200 and resp.json().get("status") == "ok"
    print(f"[4] Signed checkout webhook: {'OK' if webhook_ok else 'FAILED'} "
         f"(status={resp.status_code})")

    # 5. Assert order + customer landed in the system of record
    from backend.data.repositories.order_repository import order_repository
    order = order_repository.get_order("cs_smoke_1")
    order_ok = order is not None and order.amount == 19.99 and order.brand_id == "beauty"
    customer = order_repository.get_customer(order.customer_id) if order else None
    customer_ok = customer is not None and customer.email == "smoke@example.com"
    print(f"[5] Order recorded: {'OK' if order_ok else 'FAILED'} "
         f"(status={order.fulfillment_status if order else 'n/a'})")
    print(f"    Customer recorded: {'OK' if customer_ok else 'FAILED'} "
         f"(shipping city={customer.shipping.get('city') if customer else 'n/a'})")

    # 6. Forward the order to its supplier
    from backend.commerce.fulfillment import process_new_orders
    fulfillment_result = process_new_orders()
    order_after = order_repository.get_order("cs_smoke_1")
    placed_ok = order_after and order_after.fulfillment_status == "PLACED"
    print(f"[6] Supplier order placed: {'OK' if placed_ok else 'FAILED'} "
         f"(supplier={order_after.supplier_name if order_after else 'n/a'}, "
         f"supplier_order_id={order_after.supplier_order_id if order_after else 'n/a'})")

    # 7. Assert LTV + ROAS attribution were fed automatically
    from backend.economics.ltv import cohort_tracker
    ltv_fed = "beauty" in cohort_tracker._total_counts
    print(f"[7] LTV cohort tracker fed: {'OK' if ltv_fed else 'FAILED'}")

    from backend.commerce.orders import _get_roas_repo
    import sqlite3
    roas_repo = _get_roas_repo()
    roas_ok = False
    try:
        conn = sqlite3.connect(roas_repo.db_path)
        row = conn.execute(
            "SELECT product_id, total_price FROM orders WHERE id = ?", ("cs_smoke_1",)
        ).fetchone()
        conn.close()
        roas_ok = row is not None and row[0] == "jade-roller"
    except Exception as exc:
        print(f"    (roas check error: {exc})")
    print(f"    ROAS attribution repo fed: {'OK' if roas_ok else 'FAILED'}")

    # 8. Shadow journal check
    from backend.orchestration.event_store import event_store
    events = list(event_store._iter_events())
    has_order_received = any(e.get("event") == "order_received" for e in events)
    has_fulfillment_wf = any(e.get("workflow") == "fulfillment" for e in events)
    print(f"[8] Shadow journal: order_received={'OK' if has_order_received else 'FAILED'}, "
         f"fulfillment workflow={'OK' if has_fulfillment_wf else 'FAILED'}")

    print("=" * 60)
    all_ok = all([webhook_ok, order_ok, customer_ok, placed_ok, ltv_fed,
                  roas_ok, has_order_received, has_fulfillment_wf])
    print("RESULT:", "✅ Full closed loop verified" if all_ok else "❌ Some steps failed")
    print()
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
