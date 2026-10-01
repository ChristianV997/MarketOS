"""JSON-safe models for manually supplied Shopify-like exports.

These objects intentionally contain observations only.  They neither model nor
authorize a Shopify mutation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def _safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    return str(value)


class _Model:
    def to_dict(self) -> dict[str, Any]:
        return _safe(asdict(self))


@dataclass(frozen=True)
class ShopifyProductObservation(_Model):
    product_id: str; title: str; handle: str; vendor: str; product_type: str; status: str
    tags: tuple[str, ...]; created_at: str | None; updated_at: str | None; variant_ids: tuple[str, ...]
    collection_ids: tuple[str, ...]; image_count: int; source_url: str; raw_ref: str; metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ShopifyVariantObservation(_Model):
    variant_id: str; product_id: str; title: str; sku: str; price: float | None; compare_at_price: float | None
    inventory_quantity: int | None; inventory_policy: str; fulfillment_service: str; requires_shipping: bool
    taxable: bool; barcode_hash: str | None; weight: float | None; metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ShopifyCollectionObservation(_Model):
    collection_id: str; title: str; handle: str; product_count: int; metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ShopifyOrderObservation(_Model):
    order_id: str; order_name: str; created_at: str | None; currency: str; subtotal_price: float | None; total_price: float | None
    total_tax: float | None; total_discounts: float | None; financial_status: str; fulfillment_status: str
    line_item_ids: tuple[str, ...]; customer_ref: str | None; source_name: str; cancelled_at: str | None; metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ShopifyLineItemObservation(_Model):
    line_item_id: str; order_id: str; product_id: str | None; variant_id: str | None; title: str; sku: str
    quantity: int | None; price: float | None; total_discount: float | None; fulfillment_status: str; metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ShopifyRefundObservation(_Model):
    """Observed refund fact from a manual export. This does not issue a refund."""
    refund_id: str
    order_id: str
    created_at: str | None
    currency: str
    amount: float | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ShopifyCustomerObservation(_Model):
    customer_id: str; customer_ref: str; email_hash: str | None; phone_hash: str | None; name_redacted: str
    created_at: str | None; orders_count: int | None; total_spent: float | None; tags: tuple[str, ...]; metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ShopifyImportBatch(_Model):
    batch_id: str; workspace_id: str; source: str; mode: str; imported_at: float
    products: tuple[ShopifyProductObservation, ...]; variants: tuple[ShopifyVariantObservation, ...]
    collections: tuple[ShopifyCollectionObservation, ...]; orders: tuple[ShopifyOrderObservation, ...]
    line_items: tuple[ShopifyLineItemObservation, ...]; customers: tuple[ShopifyCustomerObservation, ...]
    warnings: tuple[str, ...] = (); skipped_records: tuple[str, ...] = (); metadata: dict[str, Any] = field(default_factory=dict)
    refunds: tuple[ShopifyRefundObservation, ...] = ()


@dataclass(frozen=True)
class ShopifyStoreContext(_Model):
    workspace_id: str; batch_id: str; product_count: int; variant_count: int; collection_count: int; order_count: int; customer_count: int
    currency_set: tuple[str, ...]; active_product_count: int; out_of_stock_variant_count: int; observed_revenue_total: float
    average_order_value: float; top_product_titles: tuple[str, ...]; warnings: tuple[str, ...]; pii_redacted: bool
    metadata: dict[str, Any] = field(default_factory=dict)


__all__ = [name for name in globals() if name.startswith("Shopify")]
