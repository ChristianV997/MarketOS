"""Fixture/manual-file Shopify export importer.  This module has no network path."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .models import (ShopifyCollectionObservation, ShopifyCustomerObservation, ShopifyImportBatch,
                     ShopifyLineItemObservation, ShopifyOrderObservation, ShopifyProductObservation,
                     ShopifyStoreContext, ShopifyVariantObservation)
from .pii import hash_pii, redact_name


def _text(value: Any, default: str = "") -> str: return str(value if value is not None else default).strip()
def _number(value: Any) -> float | None:
    try: return float(value) if value not in (None, "") else None
    except (TypeError, ValueError): return None
def _integer(value: Any) -> int | None:
    try: return int(float(value)) if value not in (None, "") else None
    except (TypeError, ValueError): return None
def _tags(value: Any) -> tuple[str, ...]:
    rows = value.split(",") if isinstance(value, str) else value if isinstance(value, list) else []
    return tuple(sorted({_text(item) for item in rows if _text(item)}))
def _rows(value: Any) -> list[dict[str, Any]]: return [item for item in (value or []) if isinstance(item, dict)]
def _stable_id(prefix: str, value: str) -> str: return f"{prefix}-{hashlib.sha256(value.encode()).hexdigest()[:16]}"
def _root(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict): return {}
    nested = data.get("data")
    return nested if isinstance(nested, dict) else data


def load_shopify_export(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict): raise ValueError("Shopify export root must be a JSON object")
    return _root(value)


def normalize_products(rows: Iterable[dict[str, Any]], source: str, limit: int | None = None) -> tuple[tuple[ShopifyProductObservation, ...], tuple[ShopifyVariantObservation, ...], list[str]]:
    products: list[ShopifyProductObservation] = []; variants: list[ShopifyVariantObservation] = []; skipped: list[str] = []
    seen: set[str] = set()
    for raw in list(rows)[:limit]:
        product_id = _text(raw.get("id"))
        title = _text(raw.get("title"))
        if not product_id or not title or product_id in seen:
            skipped.append("product_missing_id_or_title_or_duplicate"); continue
        seen.add(product_id); variant_ids: list[str] = []
        for item in _rows(raw.get("variants")):
            variant_id = _text(item.get("id"))
            if not variant_id: skipped.append(f"variant_missing_id:{product_id}"); continue
            variant_ids.append(variant_id)
            barcode = _text(item.get("barcode"))
            variants.append(ShopifyVariantObservation(variant_id, product_id, _text(item.get("title")), _text(item.get("sku")), _number(item.get("price")), _number(item.get("compare_at_price")), _integer(item.get("inventory_quantity")), _text(item.get("inventory_policy")), _text(item.get("fulfillment_service")), bool(item.get("requires_shipping", True)), bool(item.get("taxable", True)), hash_pii(barcode) if barcode else None, _number(item.get("weight")), {"read_only": True}))
        collection_ids = tuple(sorted({_text(item) for item in raw.get("collection_ids", []) if _text(item)}))
        images = raw.get("images") or []
        products.append(ShopifyProductObservation(product_id, title, _text(raw.get("handle")), _text(raw.get("vendor")), _text(raw.get("product_type")), _text(raw.get("status"), "unknown").lower(), _tags(raw.get("tags")), _text(raw.get("created_at")) or None, _text(raw.get("updated_at")) or None, tuple(variant_ids), collection_ids, len(images) if isinstance(images, list) else 0, source, f"product:{product_id}", {"read_only": True}))
    return tuple(products), tuple(variants), skipped


def normalize_orders(rows: Iterable[dict[str, Any]], limit: int | None = None) -> tuple[tuple[ShopifyOrderObservation, ...], tuple[ShopifyLineItemObservation, ...], list[str]]:
    orders: list[ShopifyOrderObservation] = []; items: list[ShopifyLineItemObservation] = []; skipped: list[str] = []; seen: set[str] = set()
    for raw in list(rows)[:limit]:
        order_id = _text(raw.get("id"))
        if not order_id or order_id in seen: skipped.append("order_missing_id_or_duplicate"); continue
        seen.add(order_id); line_ids: list[str] = []
        for index, line in enumerate(_rows(raw.get("line_items"))):
            line_id = _text(line.get("id")) or _stable_id("line", f"{order_id}:{index}:{_text(line.get('title'))}")
            line_ids.append(line_id)
            items.append(ShopifyLineItemObservation(line_id, order_id, _text(line.get("product_id")) or None, _text(line.get("variant_id")) or None, _text(line.get("title")), _text(line.get("sku")), _integer(line.get("quantity")) or 0, _number(line.get("price")), _number(line.get("total_discount")), _text(line.get("fulfillment_status") or raw.get("fulfillment_status")), {"read_only": True}))
        customer = raw.get("customer") if isinstance(raw.get("customer"), dict) else {}
        customer_id = _text(raw.get("customer_id") or customer.get("id"))
        customer_ref = f"customer:{hash_pii(customer_id)[:16]}" if customer_id else None
        orders.append(ShopifyOrderObservation(order_id, _text(raw.get("name") or raw.get("order_number") or order_id), _text(raw.get("created_at")) or None, _text(raw.get("currency"), "unknown"), _number(raw.get("subtotal_price")), _number(raw.get("total_price")), _number(raw.get("total_tax")), _number(raw.get("total_discounts")), _text(raw.get("financial_status")), _text(raw.get("fulfillment_status")), tuple(line_ids), customer_ref, _text(raw.get("source_name")), _text(raw.get("cancelled_at")) or None, {"read_only": True}))
    return tuple(orders), tuple(items), skipped


def normalize_customers(rows: Iterable[dict[str, Any]], limit: int | None = None) -> tuple[tuple[ShopifyCustomerObservation, ...], list[str]]:
    customers: list[ShopifyCustomerObservation] = []; skipped: list[str] = []; seen: set[str] = set()
    for raw in list(rows)[:limit]:
        customer_id = _text(raw.get("id"))
        if not customer_id or customer_id in seen: skipped.append("customer_missing_id_or_duplicate"); continue
        seen.add(customer_id); full_name = " ".join(item for item in (_text(raw.get("first_name")), _text(raw.get("last_name"))) if item)
        customers.append(ShopifyCustomerObservation(customer_id, f"customer:{hash_pii(customer_id)[:16]}", hash_pii(raw.get("email")), hash_pii(raw.get("phone")), redact_name(full_name), _text(raw.get("created_at")) or None, _integer(raw.get("orders_count")), _number(raw.get("total_spent")), _tags(raw.get("tags")), {"pii_redacted": True, "read_only": True}))
    return tuple(customers), skipped


def normalize_collections(rows: Iterable[dict[str, Any]], products: tuple[ShopifyProductObservation, ...], limit: int | None = None) -> tuple[tuple[ShopifyCollectionObservation, ...], list[str]]:
    values: list[ShopifyCollectionObservation] = []; skipped: list[str] = []; seen: set[str] = set()
    product_counts = Counter(item for product in products for item in product.collection_ids)
    for raw in list(rows)[:limit]:
        collection_id = _text(raw.get("id"))
        title = _text(raw.get("title"))
        if not collection_id or not title or collection_id in seen: skipped.append("collection_missing_id_or_title_or_duplicate"); continue
        seen.add(collection_id); values.append(ShopifyCollectionObservation(collection_id, title, _text(raw.get("handle")), _integer(raw.get("product_count")) or product_counts[collection_id], {"read_only": True}))
    return tuple(values), skipped


def normalize_shopify_export(data: dict[str, Any], workspace_id: str, mode: str = "fixture", limit: int | None = None, source: str = "manual://shopify-export") -> ShopifyImportBatch:
    root = _root(data); products, variants, p_skips = normalize_products(_rows(root.get("products")), source, limit)
    orders, line_items, o_skips = normalize_orders(_rows(root.get("orders")), limit)
    customers, c_skips = normalize_customers(_rows(root.get("customers")), limit)
    collections, col_skips = normalize_collections(_rows(root.get("collections")), products, limit)
    fingerprint = json.dumps(root, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(f"{workspace_id}:{mode}:{fingerprint}".encode()).hexdigest()
    warnings = ["read_only_advisory_import: no provider API was called and no mutation is possible"]
    skipped = p_skips + o_skips + c_skips + col_skips
    if skipped: warnings.append(f"skipped_records:{len(skipped)}")
    return ShopifyImportBatch(f"shopify-import-{digest[:20]}", workspace_id, source, mode, float(1_700_000_000 + int(digest[:8], 16) % 1_000_000), products, variants, collections, orders, line_items, customers, tuple(warnings), tuple(skipped), {"pii_redacted": True, "network_used": False, "provider_calls": False})


def build_store_context(batch: ShopifyImportBatch) -> ShopifyStoreContext:
    values = [order.total_price for order in batch.orders if order.total_price is not None and not order.cancelled_at]
    total = round(sum(values), 2); item_counts = Counter(item.title for item in batch.line_items if item.title)
    warnings = list(batch.warnings)
    if not batch.orders: warnings.append("no_orders_observed: no revenue or demand conclusion can be made")
    currencies = {order.currency for order in batch.orders if order.currency}
    currencies.update(refund.currency for refund in batch.refunds if refund.currency)
    metadata = {"source": batch.source, "read_only": True, "advisory": True}
    if batch.refunds:
        explicit = [refund.amount for refund in batch.refunds if refund.amount is not None]
        metadata["refund_count"] = len(batch.refunds)
        metadata["observed_refund_total"] = round(sum(explicit), 2) if explicit else None
        metadata["refund_amount_missing_count"] = sum(refund.amount is None for refund in batch.refunds)
        metadata["evidence_state"] = "manual_import"
    return ShopifyStoreContext(batch.workspace_id, batch.batch_id, len(batch.products), len(batch.variants), len(batch.collections), len(batch.orders), len(batch.customers), tuple(sorted(currencies)), sum(product.status == "active" for product in batch.products), sum(variant.inventory_quantity is not None and variant.inventory_quantity <= 0 for variant in batch.variants), total, round(total / len(values), 2) if values else 0.0, tuple(title for title, _ in item_counts.most_common(5)), tuple(warnings), True, metadata)


def import_shopify_readonly(path: str | Path, workspace_id: str = "commerce-mvp-dry-run", mode: str = "fixture", limit: int | None = None) -> tuple[ShopifyImportBatch, ShopifyStoreContext]:
    path_value = Path(path); batch = normalize_shopify_export(load_shopify_export(path_value), workspace_id, mode, limit, f"{mode}://{path_value.name}")
    return batch, build_store_context(batch)


__all__ = ["build_store_context", "import_shopify_readonly", "load_shopify_export", "normalize_collections", "normalize_customers", "normalize_orders", "normalize_products", "normalize_shopify_export"]
