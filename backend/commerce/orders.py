"""backend.commerce.orders — order ingestion funnel.

The single entry point both webhook handlers (Stripe, Shopify) funnel
into. Records the customer + order (fulfillment_status=RECEIVED), mirrors
into the existing ROAS/attribution repository so cross-platform ROAS
reconciliation keeps working with zero extra wiring, feeds the LTV cohort
tracker so repeat-purchase signal starts accumulating immediately, and
journals order_received for shadow-mode / dashboard visibility.

This module never touches payment verification or supplier fulfillment —
those are the webhook route's job (signature verification) and Phase D's
job (place_order), respectively. ingest_order() assumes the caller has
already verified the payload is authentic.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

_log = logging.getLogger(__name__)

# Cached RoasRepository instance (matches backend.workers.roas_ingestion_worker's
# constructor-param pattern rather than opening a fresh sqlite connection and
# re-running schema init on every single order — also the test-override point,
# same idiom as order_repository's module singleton).
_roas_repo = None


def _get_roas_repo():
    global _roas_repo
    if _roas_repo is None:
        from backend.data.repositories.roas_repository import RoasRepository
        _roas_repo = RoasRepository()
    return _roas_repo


def _customer_id_for(email: str, platform_customer_id: str = "") -> str:
    """Stable customer id: platform-provided id when available, else an
    email hash (so the same email always maps to the same customer_id even
    across sources that don't share a native customer id)."""
    if platform_customer_id:
        return f"cust_{platform_customer_id}"
    if email:
        return f"cust_{hashlib.md5(email.strip().lower().encode()).hexdigest()[:16]}"
    return ""


def ingest_order(source: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Ingest one completed order from a verified webhook payload.

    Expected *payload* shape (already normalized by the caller):
        {
          "order_id": str,               # unique per source; used for idempotency
          "brand_id": str, "product_id": str, "qty": int,
          "amount": float, "currency": str,
          "customer": {"email": str, "name": str, "customer_id": str (optional),
                       "shipping": {...}},
          "utm": {"utm_source": ..., ...},
          "payment_intent_id": str (optional, Stripe only — needed to map a
                                     later refund/dispute event back to this
                                     order; see reverse_order()),
        }

    Returns {status, order_id, is_new} on success, or {status: "error", ...}
    if the order/customer write itself failed (the caller — the webhook
    route — turns that into a 500 so the source retries rather than
    silently losing the order). is_new=False means the order_id was already
    recorded (webhook retry); side effects (ROAS mirror, LTV feed, journal)
    still run on a retry whenever they haven't completed yet (see
    _run_side_effects), so a crash between record_order() succeeding and
    those completing self-heals instead of skipping them forever.
    """
    from backend.data.repositories.order_repository import (
        CommerceOrder,
        CustomerRecord,
        order_repository,
    )

    order_id = str(payload.get("order_id", ""))
    if not order_id:
        return {"status": "error", "error": "missing_order_id"}

    customer_info = payload.get("customer") or {}
    email = str(customer_info.get("email", ""))
    customer_id = _customer_id_for(email, str(customer_info.get("customer_id", "")))

    try:
        if customer_id:
            order_repository.upsert_customer(CustomerRecord(
                customer_id=customer_id,
                email=email,
                name=str(customer_info.get("name", "")),
                shipping=customer_info.get("shipping") or {},
            ))

        order = CommerceOrder(
            order_id=order_id,
            source=source,
            brand_id=str(payload.get("brand_id", "")),
            product_id=str(payload.get("product_id", "")),
            qty=int(payload.get("qty", 1) or 1),
            amount=float(payload.get("amount", 0.0) or 0.0),
            currency=str(payload.get("currency", "usd")),
            customer_id=customer_id,
            utm=dict(payload.get("utm") or {}),
            payment_intent_id=str(payload.get("payment_intent_id", "")),
        )
        is_new = order_repository.record_order(order)
    except Exception as exc:
        _log.error("order_record_failed order=%s source=%s error=%s",
                   order_id, source, exc, exc_info=True)
        return {"status": "error", "error": "record_failed"}

    # Re-read from the repo rather than trusting the just-built local
    # `order`/`is_new=False` path: on a retry the stored row carries the
    # real side_effects_done state, which is what decides whether the three
    # feeds below need to run (not is_new — a crash after a successful
    # record_order() but before these complete must still retry them).
    stored = order_repository.get_order(order_id)
    if stored is not None and not stored.side_effects_done:
        _run_side_effects(stored, customer_id)

    return {"status": "ok", "order_id": order_id, "is_new": is_new}


def _run_side_effects(order: Any, customer_id: str) -> None:
    """Run the ROAS mirror + LTV feed + order_received journal, marking
    side_effects_done only if all three complete without raising.

    Safe to call repeatedly: on a retry (order already recorded but this
    never completed last time — a mid-process crash), it re-attempts from
    scratch. _mirror_to_attribution's underlying repo call is itself
    idempotent per order id, so a partial-then-retried run doesn't double
    count revenue.
    """
    from backend.data.repositories.order_repository import order_repository
    try:
        _mirror_to_attribution(order, customer_id)
        _feed_ltv(order, customer_id)
        _journal_order_received(order)
        order_repository.mark_side_effects_done(order.order_id)
    except Exception as exc:
        _log.warning("order_side_effects_incomplete order=%s error=%s",
                     order.order_id, exc, exc_info=True)


def reverse_order(order_id: str, reason: str) -> dict[str, Any]:
    """Reverse a refunded/disputed order: transition fulfillment to
    REFUNDED and emit a compensating negative entry into ROAS/LTV so
    reconciliation numbers don't stay permanently overstated by revenue
    that was later returned. Never raises; returns a status dict."""
    from backend.data.repositories.order_repository import order_repository

    order = order_repository.get_order(order_id)
    if order is None:
        return {"status": "error", "error": "unknown_order", "order_id": order_id}

    transitioned = order_repository.update_fulfillment(order_id, "REFUNDED")
    if not transitioned:
        return {"status": "error", "error": "illegal_transition", "order_id": order_id,
               "from_status": order.fulfillment_status}

    try:
        from backend.data.repositories.roas_repository import Order as RoasOrder

        repo = _get_roas_repo()
        platform = order.utm.get("utm_source", "organic") if order.utm else "organic"
        repo.ingest_orders([RoasOrder(
            id=f"refund_{order_id}",
            customer_id=order.customer_id,
            product_id=order.product_id,
            created_at=datetime.now(timezone.utc),
            total_price=-order.amount,
            source=order.source,
            platform=platform,
        )])
    except Exception:
        _log.warning("refund_attribution_reversal_failed order=%s", order_id, exc_info=True)

    try:
        from backend.orchestration.event_store import event_store, new_workflow_id
        event_store.append(
            new_workflow_id("order"), "order_refunded",
            workflow="order_intake", step="reverse",
            data={"order_id": order_id, "reason": reason, "amount": order.amount},
        )
    except Exception:
        _log.warning("order_refunded_journal_failed order=%s", order_id, exc_info=True)

    return {"status": "ok", "order_id": order_id, "fulfillment_status": "REFUNDED"}


def _mirror_to_attribution(order: Any, customer_id: str) -> None:
    """Feed the order into the existing ROAS/cross-platform attribution repo
    so reconciliation keeps working without any extra wiring."""
    try:
        from backend.data.repositories.roas_repository import Order as RoasOrder

        repo = _get_roas_repo()
        platform = order.utm.get("utm_source", "organic") if order.utm else "organic"
        repo.ingest_orders([RoasOrder(
            id=order.order_id,
            customer_id=customer_id,
            product_id=order.product_id,
            created_at=datetime.now(timezone.utc),
            total_price=order.amount,
            source=order.source,
            platform=platform,
        )])
    except Exception:
        _log.warning("attribution_mirror_failed order=%s", order.order_id, exc_info=True)
        raise


def _feed_ltv(order: Any, customer_id: str) -> None:
    """Feed the LTV cohort tracker so repeat-rate signal accumulates."""
    try:
        from backend.economics.ltv import cohort_tracker
        from backend.commerce.catalog import product_catalog

        entry = product_catalog.get(order.product_id)
        category = "general"
        try:
            from backend.commerce.brands import brand_registry
            brand = brand_registry.get(entry.brand_id) if entry else None
            if brand:
                category = brand.category
        except Exception:
            pass
        cohort_tracker.record_order(customer_id, category, order_id=order.order_id)
    except Exception:
        _log.warning("ltv_feed_failed order=%s", order.order_id, exc_info=True)
        raise


def _journal_order_received(order: Any) -> None:
    try:
        from backend.orchestration.event_store import event_store, new_workflow_id
        event_store.append(
            new_workflow_id("order"), "order_received",
            workflow="order_intake", step="ingest",
            data={
                "order_id": order.order_id, "source": order.source,
                "brand_id": order.brand_id, "product_id": order.product_id,
                "qty": order.qty, "amount": order.amount,
                "utm": order.utm,
            },
        )
    except Exception:
        _log.warning("order_received_journal_failed order=%s", order.order_id, exc_info=True)
        raise
