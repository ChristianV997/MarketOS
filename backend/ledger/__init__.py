"""backend.ledger — the canonical, event-sourced commerce ledger.

Raw commerce events (backend.ledger.events) are appended to the same
durable, append-only log every other dry-run/shadow gate in this repo
already writes to (backend.orchestration.event_store) — no second event
log. backend.ledger.projections replays that stream, scoped per
workspace_id, into the derived numbers (recognized revenue, cash
collected, CAC variants, contribution profit, ...) that
services.unit_economics and services.ecommerce_operator can consume via
their from_ledger() entry points instead of requiring the caller to
supply pre-aggregated scalars by hand.
"""
from __future__ import annotations

from .events import (
    EVENT_TYPES,
    record_ad_spend_observed,
    record_attribution_claim_observed,
    record_chargeback_opened,
    record_fulfillment_completed,
    record_order_canceled,
    record_order_created,
    record_payment_captured,
    record_refund_issued,
    record_supplier_cost_observed,
)
from .projections import LedgerSnapshot, compute_projection

__all__ = [
    "EVENT_TYPES",
    "record_order_created",
    "record_payment_captured",
    "record_order_canceled",
    "record_refund_issued",
    "record_chargeback_opened",
    "record_supplier_cost_observed",
    "record_fulfillment_completed",
    "record_ad_spend_observed",
    "record_attribution_claim_observed",
    "LedgerSnapshot",
    "compute_projection",
]
