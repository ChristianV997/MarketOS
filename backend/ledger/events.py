"""backend.ledger.events — the canonical commerce-event vocabulary.

Every function here does exactly one thing: append one structured, typed
event to the existing backend.orchestration.event_store (the same durable
JSONL log every dry-run/shadow gate already writes to — no new log file).
Nothing here computes anything; backend.ledger.projections is the only
place that derives numbers by replaying these events.

Never raises: matches this repo's "never raise in the money path"
principle. A failed append is logged and swallowed — the caller (a
webhook handler, a CLI import, a test) should never see an exception from
recording a fact that already happened.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from backend.orchestration.event_store import event_store, new_workflow_id

_log = logging.getLogger(__name__)

EVENT_TYPES = (
    "OrderCreated",
    "PaymentCaptured",
    "OrderCanceled",
    "RefundIssued",
    "ChargebackOpened",
    "SupplierCostObserved",
    "FulfillmentCompleted",
    "AdSpendObserved",
    "AttributionClaimObserved",
)


def _record(event_type: str, workspace_id: str, **data: Any) -> dict:
    """Append one ledger event; never raises."""
    try:
        payload = {"workspace_id": workspace_id, "ts": time.time(), **data}
        return event_store.append(
            new_workflow_id("ledger"), event_type,
            workflow="commerce_ledger", step=workspace_id, data=payload,
        )
    except Exception as exc:  # noqa: BLE001 — recording a fact must never raise
        _log.warning("ledger_event_append_failed event=%s workspace=%s error=%s",
                     event_type, workspace_id, exc)
        return {}


def record_order_created(workspace_id: str, order_id: str, *, product_name: str = "",
                          category: str = "general", channel: str = "",
                          revenue: float = 0.0) -> dict:
    return _record("OrderCreated", workspace_id, order_id=order_id,
                    product_name=product_name, category=category,
                    channel=channel, revenue=round(revenue, 2))


def record_payment_captured(workspace_id: str, order_id: str, *, amount: float = 0.0) -> dict:
    return _record("PaymentCaptured", workspace_id, order_id=order_id, amount=round(amount, 2))


def record_order_canceled(workspace_id: str, order_id: str, *, reason: str = "") -> dict:
    return _record("OrderCanceled", workspace_id, order_id=order_id, reason=reason)


def record_refund_issued(workspace_id: str, order_id: str, *, amount: float = 0.0) -> dict:
    return _record("RefundIssued", workspace_id, order_id=order_id, amount=round(amount, 2))


def record_chargeback_opened(workspace_id: str, order_id: str, *, amount: float = 0.0) -> dict:
    return _record("ChargebackOpened", workspace_id, order_id=order_id, amount=round(amount, 2))


def record_supplier_cost_observed(workspace_id: str, order_id: str, *,
                                   product_name: str = "", amount: float = 0.0) -> dict:
    return _record("SupplierCostObserved", workspace_id, order_id=order_id,
                    product_name=product_name, amount=round(amount, 2))


def record_fulfillment_completed(workspace_id: str, order_id: str) -> dict:
    return _record("FulfillmentCompleted", workspace_id, order_id=order_id)


def record_ad_spend_observed(workspace_id: str, *, channel: str = "", amount: float = 0.0,
                              product_name: str = "") -> dict:
    return _record("AdSpendObserved", workspace_id, channel=channel,
                    amount=round(amount, 2), product_name=product_name)


def record_attribution_claim_observed(workspace_id: str, order_id: str, *,
                                       channel: str = "", claimed_revenue: float = 0.0) -> dict:
    return _record("AttributionClaimObserved", workspace_id, order_id=order_id,
                    channel=channel, claimed_revenue=round(claimed_revenue, 2))
