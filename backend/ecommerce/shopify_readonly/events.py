"""Canonical, non-authoritative events for manual Shopify import observations."""
from __future__ import annotations

import hashlib
from typing import Any

from backend.contracts.events import Event
from backend.events.repository import EventRepository

from .models import ShopifyImportBatch, ShopifyStoreContext


_SAFETY = {
    "dry_run": True, "advisory": True, "read_only": True, "non_authoritative": True,
    "pii_redacted": True, "no_mutation": True, "no_publish_authority": True,
    "no_store_mutation_authority": True, "no_inventory_mutation_authority": True,
    "no_fulfillment_authority": True, "no_payment_authority": True,
    "no_refund_authority": True, "no_customer_message_authority": True,
}


def _event(batch: ShopifyImportBatch, index: int, event_type: str, aggregate_type: str, aggregate_id: str, payload: dict[str, Any]) -> Event:
    event_id = "shopify-readonly-event-" + hashlib.sha256(f"{batch.batch_id}:{index}:{event_type}:{aggregate_id}".encode()).hexdigest()[:20]
    return Event(event_id, batch.workspace_id, aggregate_type, aggregate_id, event_type, 1, batch.imported_at + index / 1000,
                 correlation_id=batch.batch_id, source="backend.ecommerce.shopify_readonly", payload=payload,
                 metadata={**_SAFETY, "import_batch_id": batch.batch_id, "import_mode": batch.mode, "source": batch.source})


def shopify_batch_events(batch: ShopifyImportBatch, context: ShopifyStoreContext) -> list[Event]:
    rows: list[tuple[str, str, str, dict[str, Any]]] = [
        ("shopify_import_batch_started", "shopify_import_batch", batch.batch_id, {"source": batch.source, "mode": batch.mode}),
        *[("shopify_product_observed", "shopify_product", item.product_id, item.to_dict()) for item in batch.products],
        *[("shopify_variant_observed", "shopify_variant", item.variant_id, item.to_dict()) for item in batch.variants],
        *[("shopify_collection_observed", "shopify_collection", item.collection_id, item.to_dict()) for item in batch.collections],
        *[("shopify_order_observed", "shopify_order", item.order_id, item.to_dict()) for item in batch.orders],
        *[("shopify_refund_observed", "shopify_refund", item.refund_id, item.to_dict()) for item in batch.refunds],
        *[("shopify_line_item_observed", "shopify_line_item", item.line_item_id, item.to_dict()) for item in batch.line_items],
        *[("shopify_customer_observed", "shopify_customer", item.customer_id, item.to_dict()) for item in batch.customers],
        ("shopify_store_context_built", "shopify_store_context", context.batch_id, context.to_dict()),
        ("shopify_import_batch_completed", "shopify_import_batch", batch.batch_id, {"warnings": list(batch.warnings), "skipped_records": list(batch.skipped_records)}),
    ]
    return [_event(batch, index, *row) for index, row in enumerate(rows)]


def append_shopify_events(batch: ShopifyImportBatch, context: ShopifyStoreContext, repository: EventRepository) -> list[str]:
    events = shopify_batch_events(batch, context)
    repository.append_many(events)
    return [item.event_id for item in events]


def event_type_counts(events: list[Event]) -> dict[str, int]:
    values: dict[str, int] = {}
    for event in events: values[event.event_type] = values.get(event.event_type, 0) + 1
    return dict(sorted(values.items()))


__all__ = ["append_shopify_events", "event_type_counts", "shopify_batch_events"]
