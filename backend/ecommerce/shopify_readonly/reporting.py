"""Stable JSON/Markdown reporting for Shopify read-only import packets."""
from __future__ import annotations

from typing import Any

from .events import event_type_counts, shopify_batch_events
from .models import ShopifyImportBatch, ShopifyStoreContext


def report_to_dict(batch: ShopifyImportBatch, context: ShopifyStoreContext) -> dict[str, Any]:
    events = shopify_batch_events(batch, context)
    return {"workspace_id": batch.workspace_id, "source": batch.source, "mode": batch.mode, "product_count": len(batch.products), "variant_count": len(batch.variants), "collection_count": len(batch.collections), "order_count": len(batch.orders), "line_item_count": len(batch.line_items), "customer_count": len(batch.customers), "skipped_count": len(batch.skipped_records), "warnings": list(context.warnings), "observed_revenue_total": context.observed_revenue_total, "average_order_value": context.average_order_value, "active_product_count": context.active_product_count, "out_of_stock_variant_count": context.out_of_stock_variant_count, "pii_redacted": context.pii_redacted, "canonical_event_count": len(events), "event_type_counts": event_type_counts(events), "forbidden_actions": ["create_product", "update_product", "publish_product", "mutate_inventory", "create_order", "capture_payment", "refund", "fulfill", "message_customer"], "next_recommended_step": "Review the PII-redacted packet manually; future authenticated read-only access requires explicit least-privilege scope review.", "network_calls": False, "mutated": False}


def report_to_markdown(batch: ShopifyImportBatch, context: ShopifyStoreContext) -> str:
    report = report_to_dict(batch, context)
    return "\n".join(["# Shopify read-only import packet", "", f"- Workspace: `{report['workspace_id']}`", f"- Products / orders: {report['product_count']} / {report['order_count']}", f"- PII redacted: `{report['pii_redacted']}`", "", "## Safety", "", "- Manual/fixture input only. No Shopify API call, mutation, publishing, payment, fulfillment, refund, or customer message was executed.", "", "## Context", "", f"- Observed revenue total: {report['observed_revenue_total']} (historical export context only; not a forecast)", f"- Observed AOV: {report['average_order_value']} (not a profitability or demand claim)", ""]) + "\n"


__all__ = ["report_to_dict", "report_to_markdown"]
