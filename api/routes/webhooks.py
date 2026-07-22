"""api.routes.webhooks — signed order/payment webhook receivers.

Two sources funnel into backend.commerce.orders.ingest_order:
  POST /webhooks/stripe   — checkout.session.completed (Stripe Checkout)
  POST /webhooks/shopify  — orders/create (for brands bound to Shopify)

Security invariant, non-negotiable: fulfillment is triggered ONLY from a
verified webhook, NEVER from a checkout success redirect. A customer can
freely visit the success URL without having paid; only a signed
server-to-server event proves money moved. If the relevant secret isn't
configured, the endpoint refuses everything (503) rather than accepting
unsigned payloads.

Local testing (Stripe):
    stripe listen --forward-to localhost:8000/webhooks/stripe
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time

from fastapi import APIRouter, Header, HTTPException, Request

_log = logging.getLogger(__name__)

router = APIRouter()

_STRIPE_TOLERANCE_S = 300


def _verify_stripe_signature(payload: bytes, sig_header: str, secret: str) -> bool:
    """Verify a Stripe webhook signature (stdlib hmac — no stripe SDK needed).

    Header shape: "t=<timestamp>,v1=<signature>[,v1=<signature>...]"
    Signed payload is "{timestamp}.{body}", HMAC-SHA256 with the secret.
    """
    parts: dict[str, list[str]] = {}
    for item in sig_header.split(","):
        if "=" not in item:
            continue
        k, v = item.split("=", 1)
        parts.setdefault(k.strip(), []).append(v.strip())

    timestamps = parts.get("t", [])
    signatures = parts.get("v1", [])
    if not timestamps or not signatures:
        return False

    try:
        ts = int(timestamps[0])
    except ValueError:
        return False
    if abs(time.time() - ts) > _STRIPE_TOLERANCE_S:
        return False

    signed_payload = f"{ts}.".encode() + payload
    expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, sig) for sig in signatures)


def _verify_shopify_signature(payload: bytes, hmac_header: str, secret: str) -> bool:
    import base64
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(expected, hmac_header)


@router.post("/webhooks/stripe")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(default="", alias="Stripe-Signature"),
):
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    if not secret:
        # Never accept unsigned payloads — refuse outright rather than
        # silently trust an unverifiable webhook.
        raise HTTPException(status_code=503, detail="stripe_webhook_not_configured")

    body = await request.body()
    if not stripe_signature or not _verify_stripe_signature(body, stripe_signature, secret):
        raise HTTPException(status_code=400, detail="invalid_signature")

    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid_payload")

    event_id = str(event.get("id", ""))
    event_type = str(event.get("type", ""))

    from backend.data.repositories.order_repository import order_repository
    if event_id and not order_repository.mark_event_seen(event_id, source="stripe"):
        return {"status": "ok", "duplicate": True}

    if event_type != "checkout.session.completed":
        return {"status": "ok", "ignored": event_type}

    session = event.get("data", {}).get("object", {})
    metadata = session.get("metadata", {}) or {}
    shipping = (session.get("shipping_details") or {}).get("address", {}) or {}
    customer_details = session.get("customer_details", {}) or {}

    payload = {
        "order_id": str(session.get("id", event_id)),
        "brand_id": str(metadata.get("brand_id", "")),
        "product_id": str(metadata.get("product_id", "")),
        "qty": int(metadata.get("qty", 1) or 1),
        "amount": float(session.get("amount_total", 0) or 0) / 100.0,
        "currency": str(session.get("currency", "usd")),
        "customer": {
            "email": str(customer_details.get("email", "")),
            "name": str(customer_details.get("name", "")),
            "shipping": {
                "line1": shipping.get("line1", ""),
                "line2": shipping.get("line2", ""),
                "city": shipping.get("city", ""),
                "state": shipping.get("state", ""),
                "postal_code": shipping.get("postal_code", ""),
                "country": shipping.get("country", ""),
            },
        },
        "utm": {k: v for k, v in metadata.items() if k.startswith("utm_")},
    }

    from backend.commerce.orders import ingest_order
    result = ingest_order("stripe", payload)
    return result


@router.post("/webhooks/shopify")
async def shopify_webhook(
    request: Request,
    x_shopify_hmac_sha256: str = Header(default="", alias="X-Shopify-Hmac-Sha256"),
    x_shopify_topic: str = Header(default="", alias="X-Shopify-Topic"),
):
    secret = os.getenv("SHOPIFY_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(status_code=503, detail="shopify_webhook_not_configured")

    body = await request.body()
    if not x_shopify_hmac_sha256 or not _verify_shopify_signature(
        body, x_shopify_hmac_sha256, secret
    ):
        raise HTTPException(status_code=400, detail="invalid_signature")

    if x_shopify_topic and x_shopify_topic != "orders/create":
        return {"status": "ok", "ignored": x_shopify_topic}

    try:
        order = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid_payload")

    from backend.data.repositories.order_repository import order_repository
    order_id = str(order.get("id", ""))
    if order_id and not order_repository.mark_event_seen(f"shopify_{order_id}", source="shopify"):
        return {"status": "ok", "duplicate": True}

    line_items = order.get("line_items") or [{}]
    first_item = line_items[0]
    customer = order.get("customer") or {}
    shipping = order.get("shipping_address") or {}
    note_attrs = {a.get("name", ""): a.get("value", "")
                  for a in (order.get("note_attributes") or [])}

    payload = {
        "order_id": order_id,
        "brand_id": str(note_attrs.get("brand_id", "")),
        "product_id": str(first_item.get("sku", first_item.get("product_id", ""))),
        "qty": int(first_item.get("quantity", 1) or 1),
        "amount": float(order.get("total_price", 0.0) or 0.0),
        "currency": str(order.get("currency", "usd")),
        "customer": {
            "email": str(order.get("email", customer.get("email", ""))),
            "name": f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip(),
            "customer_id": str(customer.get("id", "")),
            "shipping": {
                "line1": shipping.get("address1", ""),
                "line2": shipping.get("address2", ""),
                "city": shipping.get("city", ""),
                "state": shipping.get("province", ""),
                "postal_code": shipping.get("zip", ""),
                "country": shipping.get("country", ""),
            },
        },
        "utm": {k: v for k, v in note_attrs.items() if k.startswith("utm_")},
    }

    from backend.commerce.orders import ingest_order
    result = ingest_order("shopify", payload)
    return result
