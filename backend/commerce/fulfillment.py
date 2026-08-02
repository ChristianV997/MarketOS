"""backend.commerce.fulfillment — order routing + supplier forwarding.

The last leg of the closed loop: a RECEIVED order (customer paid, we have
their shipping address) gets routed to the product's bound supplier and
placed. Every placement is journaled as a workflow_started/step_completed
(or step_failed)/workflow_completed(or workflow_failed) sequence — exactly
what backend.orchestration.event_store.incomplete_workflows() needs to
surface a crash mid-placement on restart, and placement is idempotent
(SupplierClient derives supplier_order_id from our own order_id, so a
retry after a crash resolves to the same id rather than double-ordering).

FULFILLMENT_LIVE=false (default): process_new_orders() still calls
place_order() (which is itself gated by the separate SUPPLIER_ORDERS_DRY_RUN
flag — quotes going live never implies orders going live) and advances the
state machine with the dry supplier_order_id — a full rehearsal of the
routing + state-machine logic with zero real spend.
"""
from __future__ import annotations

import logging
import os
from typing import Any

_log = logging.getLogger(__name__)

# After this many consecutive poll_placed_orders() errors for the same
# order, stop polling silently and escalate to FAILED (which retry_failed_orders
# then picks up) instead of stalling in PLACED forever with no signal.
_MAX_POLL_FAILURES = int(os.getenv("FULFILLMENT_POLL_FAILURE_LIMIT", "5"))
# Cap on FAILED->PLACED retry attempts before an order is left FAILED for
# good (surfaced via the Tier 3 supplier_placement_failures alert).
_MAX_FULFILLMENT_ATTEMPTS = int(os.getenv("FULFILLMENT_MAX_ATTEMPTS", "3"))


def _live() -> bool:
    from backend.research.mode import is_research_only
    return not is_research_only() and os.getenv("FULFILLMENT_LIVE", "false").lower() == "true"


def route_order(order: Any) -> Any | None:
    """Pick the supplier client for *order*'s product.

    Priority: the catalog entry's bound supplier -> the brand's
    supplier_bindings (first one registered) -> find_best_supplier() as a
    last resort. Returns a SupplierClient or None if nothing resolves.
    """
    from backend.validation.suppliers import find_best_supplier, get_client

    try:
        from backend.commerce.catalog import product_catalog
        entry = product_catalog.get(order.product_id)
    except Exception:
        entry = None

    if entry and entry.supplier:
        client = get_client(entry.supplier)
        if client:
            return client

    try:
        from backend.commerce.brands import brand_registry
        brand = brand_registry.get(order.brand_id)
        if brand:
            for name in brand.supplier_bindings:
                client = get_client(name)
                if client:
                    return client
    except Exception:
        pass

    try:
        quote = find_best_supplier(entry.title if entry else order.product_id)
    except Exception:
        # _place_one_order's docstring promises "never raises" — a bad
        # quote lookup here must not propagate out of process_new_orders()'s
        # list comprehension and abort the rest of the batch silently.
        _log.warning("route_order_fallback_quote_failed order=%s", order.order_id,
                    exc_info=True)
        quote = None
    if quote:
        return get_client(quote.supplier)
    return None


def _journal_workflow(workflow_id: str, event: str, **data) -> None:
    try:
        from backend.orchestration.event_store import event_store
        event_store.append(workflow_id, event, workflow="fulfillment",
                           step="place_order", data=data)
    except Exception:
        _log.warning("fulfillment_journal_failed workflow_id=%s event=%s",
                    workflow_id, event, exc_info=True)


def _place_one_order(order: Any) -> dict[str, Any]:
    """Route + place a single RECEIVED order. Returns a result dict; never raises."""
    from backend.data.repositories.order_repository import order_repository
    from backend.orchestration.event_store import new_workflow_id

    workflow_id = new_workflow_id("fulfillment")
    _journal_workflow(workflow_id, "workflow_started",
                      order_id=order.order_id, brand_id=order.brand_id,
                      product_id=order.product_id)

    client = route_order(order)
    if client is None:
        _journal_workflow(workflow_id, "workflow_failed",
                          order_id=order.order_id, reason="no_supplier_bound")
        if _live():
            order_repository.update_fulfillment(order.order_id, "FAILED")
        return {"order_id": order.order_id, "status": "no_supplier"}

    order_repository.increment_fulfillment_attempts(order.order_id)

    from backend.commerce.catalog import product_catalog
    entry = product_catalog.get(order.product_id)
    customer = order_repository.get_customer(order.customer_id)

    supplier_order = {
        "order_id": order.order_id,
        "supplier_product_id": entry.supplier_product_id if entry else "",
        "qty": order.qty,
        "shipping": customer.shipping if customer else {},
    }

    result = client.place_order(supplier_order)
    live = _live()

    if result.get("status") == "ok":
        _journal_workflow(workflow_id, "step_completed",
                          order_id=order.order_id, supplier=client.name,
                          supplier_order_id=result["supplier_order_id"],
                          dry_run=result.get("dry_run", True), live=live)
        _journal_workflow(workflow_id, "workflow_completed",
                          order_id=order.order_id, live=live)
        if live or result.get("dry_run"):
            # Advance the state machine either way — dry-run rehearsals need
            # the transition to exercise poll_placed_orders() downstream too.
            order_repository.update_fulfillment(
                order.order_id, "PLACED",
                supplier_name=client.name,
                supplier_order_id=result["supplier_order_id"],
            )
        return {"order_id": order.order_id, "status": "placed",
               "supplier": client.name, "live": live}

    _journal_workflow(workflow_id, "step_failed",
                      order_id=order.order_id, supplier=client.name,
                      error=result.get("error", ""))
    _journal_workflow(workflow_id, "workflow_failed",
                      order_id=order.order_id, reason=result.get("error", ""))
    if live:
        order_repository.update_fulfillment(order.order_id, "FAILED")
    return {"order_id": order.order_id, "status": "failed",
           "error": result.get("error", "")}


def process_new_orders(limit: int = 50) -> dict[str, Any]:
    """Route + place every RECEIVED order. Returns a summary dict."""
    from backend.data.repositories.order_repository import order_repository

    orders = order_repository.orders_by_status("RECEIVED", limit=limit)
    if not orders:
        return {"status": "skipped", "reason": "no_new_orders"}

    results = [_place_one_order(o) for o in orders]
    placed = sum(1 for r in results if r["status"] == "placed")
    failed = sum(1 for r in results if r["status"] in ("failed", "no_supplier"))

    return {"status": "ok", "processed": len(results),
           "placed": placed, "failed": failed, "results": results}


def retry_failed_orders(limit: int = 50, max_attempts: int = _MAX_FULFILLMENT_ATTEMPTS) -> dict[str, Any]:
    """Re-attempt placement for FAILED orders — the state machine has always
    allowed FAILED->PLACED, but nothing called it, so an order that failed
    routing/placement (transient supplier error, brief no-supplier-bound
    window) was stranded forever. Capped by fulfillment_attempts so a
    permanently broken order doesn't retry indefinitely; orders at the cap
    are left FAILED and surface via the supplier_placement_failures alert."""
    from backend.data.repositories.order_repository import order_repository

    orders = order_repository.orders_by_status("FAILED", limit=limit)
    if not orders:
        return {"status": "skipped", "reason": "no_failed_orders"}

    retried = 0
    exhausted = 0
    results = []
    for order in orders:
        if order.fulfillment_attempts >= max_attempts:
            exhausted += 1
            continue
        result = _place_one_order(order)
        results.append(result)
        if result["status"] == "placed":
            retried += 1

    return {"status": "ok", "checked": len(orders), "retried": retried,
           "exhausted": exhausted, "results": results}


def poll_placed_orders(limit: int = 50) -> dict[str, Any]:
    """Poll supplier status for every PLACED order, advancing SHIPPED/DELIVERED.

    Feeds observed delays/failures into the existing supplier reliability
    EMA (backend.economics.supplier_feedback) on terminal outcomes.
    """
    from backend.data.repositories.order_repository import order_repository
    from backend.validation.suppliers import get_client

    orders = order_repository.orders_by_status("PLACED", limit=limit)
    if not orders:
        return {"status": "skipped", "reason": "no_placed_orders"}

    advanced = 0
    escalated = 0
    for order in orders:
        client = get_client(order.supplier_name)
        if client is None or not order.supplier_order_id:
            continue
        try:
            status = client.order_status(order.supplier_order_id)
        except Exception as exc:
            failures = order_repository.increment_poll_failures(order.order_id)
            _log.warning("supplier_status_poll_failed order=%s supplier=%s "
                        "consecutive_failures=%d error=%s",
                        order.order_id, order.supplier_name, failures, exc)
            if failures >= _MAX_POLL_FAILURES:
                # Repeated polling errors are indistinguishable from a
                # genuinely stuck order — stop stalling silently in PLACED
                # and let retry_failed_orders() (and the Tier 3 alert) take
                # over rather than nothing ever noticing.
                order_repository.update_fulfillment(order.order_id, "FAILED")
                _feed_supplier_reliability(order, delivered=False)
                escalated += 1
            continue

        if order.poll_failures:
            order_repository.reset_poll_failures(order.order_id)

        mapped = status.get("status", "")
        if mapped == "shipped":
            order_repository.update_fulfillment(order.order_id, "SHIPPED")
            advanced += 1
        elif mapped == "delivered":
            order_repository.update_fulfillment(order.order_id, "DELIVERED")
            advanced += 1
            _feed_supplier_reliability(order, delivered=True)
        elif mapped == "failed":
            order_repository.update_fulfillment(order.order_id, "FAILED")
            advanced += 1
            _feed_supplier_reliability(order, delivered=False)
        elif mapped == "unknown":
            _log.warning("supplier_status_unrecognized order=%s supplier=%s "
                        "supplier_order_id=%s", order.order_id,
                        order.supplier_name, order.supplier_order_id)

    return {"status": "ok" if (advanced or escalated) else "skipped",
           "checked": len(orders), "advanced": advanced, "escalated": escalated}


def _feed_supplier_reliability(order: Any, delivered: bool) -> None:
    try:
        from backend.economics.supplier_feedback import supplier_feedback
        from backend.commerce.catalog import product_catalog
        from backend.commerce.brands import brand_registry

        entry = product_catalog.get(order.product_id)
        category = "general"
        if entry:
            brand = brand_registry.get(entry.brand_id)
            if brand:
                category = brand.category
        supplier_feedback.record_outcome(
            order.supplier_name, category, stockout=not delivered,
        )
    except Exception:
        _log.debug("supplier_reliability_feed_failed order=%s", order.order_id,
                  exc_info=True)
