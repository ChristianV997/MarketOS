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

import base64
import hashlib
import hmac
import json
import logging
import os

import stripe
from fastapi import APIRouter, Header, HTTPException, Request

_log = logging.getLogger(__name__)

router = APIRouter()

_STRIPE_TOLERANCE_S = 300


def _verify_stripe_signature(payload: bytes, sig_header: str, secret: str) -> bool:
    """Verify a Stripe webhook signature via the official stripe SDK.

    Delegates to ``stripe.Webhook.construct_event`` (constant-time
    comparison, timestamp-tolerance check, "t=<ts>,v1=<sig>[,v1=<sig>...]"
    header parsing) rather than hand-rolling the HMAC-SHA256 check — same
    tolerance window (300s) as before. Only the boolean result is used
    here; the parsed Event object is discarded since the caller already
    re-parses the raw body as a plain dict downstream.
    """
    try:
        stripe.Webhook.construct_event(payload, sig_header, secret, tolerance=_STRIPE_TOLERANCE_S)
        return True
    except (ValueError, stripe.error.SignatureVerificationError):
        return False


def _verify_shopify_signature(payload: bytes, hmac_header: str, secret: str) -> bool:
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(expected, hmac_header)


def _journal_signature_failure(source: str) -> None:
    """Feeds the webhook_signature_failures alert (backend.monitoring.alerts)
    — a burst of these is either a misconfigured webhook secret or an
    attacker probing the endpoint, and previously there was no signal
    anywhere that it was happening at all."""
    try:
        from backend.orchestration.event_store import event_store, new_workflow_id
        event_store.append(new_workflow_id("webhooksig"), "webhook_signature_failed",
                           workflow="webhook_security", step="verify",
                           data={"source": source})
    except Exception:
        _log.warning("webhook_signature_failure_journal_failed source=%s", source,
                    exc_info=True)


# Event types this route understands. Anything else falls through to the
# generic {"ignored": event_type} branch — that's fine (Stripe sends many
# event types we don't act on), but these are the ones with money-safety
# implications, so they get explicit handling rather than silent ignoring.
_ORDER_EVENT_TYPES = {"checkout.session.completed", "checkout.session.async_payment_succeeded"}
_NO_OP_EVENT_TYPES = {"checkout.session.async_payment_failed", "checkout.session.expired"}
_REVERSAL_EVENT_TYPES = {"charge.refunded", "payment_intent.payment_failed", "charge.dispute.created"}


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
        _journal_signature_failure("stripe")
        raise HTTPException(status_code=400, detail="invalid_signature")

    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid_payload")

    event_id = str(event.get("id", ""))
    event_type = str(event.get("type", ""))

    from backend.data.repositories.order_repository import order_repository

    # Peek (read-only) rather than mark-then-process: marking the event seen
    # BEFORE processing means any transient failure during processing (a
    # locked sqlite write, a malformed metadata field) previously caused a
    # permanent silent order loss — Stripe retries the same event id, the
    # retry sees "already seen" and short-circuits, and ingest_order() never
    # runs a second time despite the customer having paid. Only mark seen
    # once processing actually succeeds, below.
    if event_id and order_repository.event_already_seen(event_id):
        return {"status": "ok", "duplicate": True}

    try:
        if event_type in _ORDER_EVENT_TYPES:
            result = _handle_stripe_order_event(event_type, event, event_id)
        elif event_type in _NO_OP_EVENT_TYPES:
            result = {"status": "ok", "ignored": event_type}
        elif event_type in _REVERSAL_EVENT_TYPES:
            result = _handle_stripe_reversal_event(event_type, event)
        else:
            result = {"status": "ok", "ignored": event_type}
    except Exception as exc:
        _log.error("stripe_webhook_processing_failed event_id=%s type=%s error=%s",
                  event_id, event_type, exc, exc_info=True)
        # 500, not a swallowed error: Stripe retries on any non-2xx, and the
        # event hasn't been marked seen, so the retry actually reprocesses.
        raise HTTPException(status_code=500, detail="processing_failed")

    if event_id:
        order_repository.mark_event_seen(event_id, source="stripe")
    return result


def _handle_stripe_order_event(event_type: str, event: dict, event_id: str) -> dict:
    session = event.get("data", {}).get("object", {})

    # checkout.session.completed fires once the *session* is done, which for
    # delayed payment methods (ACH debit, SEPA, ...) can be BEFORE the
    # *payment* actually settles — payment_status stays "unpaid" until the
    # async event below. Ingesting here would place a supplier order (real
    # spend) against payment that hasn't happened yet.
    if event_type == "checkout.session.completed":
        payment_status = session.get("payment_status", "paid")
        if payment_status == "unpaid":
            return {"status": "ok", "ignored": "payment_pending"}

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
        "payment_intent_id": str(session.get("payment_intent", "")),
    }

    from backend.commerce.orders import ingest_order
    result = ingest_order("stripe", payload)
    if result.get("status") != "ok":
        raise RuntimeError(f"ingest_order_failed: {result.get('error')}")
    return result


def _handle_stripe_reversal_event(event_type: str, event: dict) -> dict:
    """charge.refunded / payment_intent.payment_failed / charge.dispute.created
    all reference a PaymentIntent (directly, or via the charge/dispute's own
    payment_intent field) rather than our Checkout-Session-derived order_id —
    look the order up by that and reverse it."""
    obj = event.get("data", {}).get("object", {})
    if event_type == "payment_intent.payment_failed":
        payment_intent_id = str(obj.get("id", ""))
    else:
        payment_intent_id = str(obj.get("payment_intent", ""))

    if not payment_intent_id:
        return {"status": "ok", "ignored": f"{event_type}_no_payment_intent"}

    from backend.data.repositories.order_repository import order_repository
    order = order_repository.get_order_by_payment_intent(payment_intent_id)
    if order is None:
        # Nothing on our side to reverse (e.g. a failed PaymentIntent whose
        # Checkout Session never completed) — not an error.
        return {"status": "ok", "ignored": f"{event_type}_no_matching_order"}

    from backend.commerce.orders import reverse_order
    return reverse_order(order.order_id, reason=event_type)


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
        _journal_signature_failure("shopify")
        raise HTTPException(status_code=400, detail="invalid_signature")

    if x_shopify_topic and x_shopify_topic != "orders/create":
        return {"status": "ok", "ignored": x_shopify_topic}

    try:
        order = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid_payload")

    from backend.data.repositories.order_repository import order_repository
    order_id = str(order.get("id", ""))
    dedupe_key = f"shopify_{order_id}"
    if order_id and order_repository.event_already_seen(dedupe_key):
        return {"status": "ok", "duplicate": True}

    try:
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
        if result.get("status") != "ok":
            raise RuntimeError(f"ingest_order_failed: {result.get('error')}")
    except Exception as exc:
        _log.error("shopify_webhook_processing_failed order_id=%s error=%s",
                  order_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="processing_failed")

    if order_id:
        order_repository.mark_event_seen(dedupe_key, source="shopify")
    return result
