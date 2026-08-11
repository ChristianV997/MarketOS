"""Explicitly gated, read-only CJ catalog evidence adapter.

The adapter reuses ``CJDropshippingClient``'s existing token exchange and
restricts calls to the documented product/list, product/query, and stock GET
endpoints. It never exposes or stores credentials and never reaches order,
payment, logistics-write, or fulfillment operations.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Mapping

from backend.adapters.research.cj_public_evidence import CJProductEvidence
from backend.validation.suppliers import CJDropshippingClient

SOURCE = "cj_authenticated_api"
PROVIDER = "cj"
LIVE_FLAG = "MARKETOS_SUPPLIER_AUTH_READONLY"
PROVIDER_ENV = "MARKETOS_SUPPLIER_PROVIDER"
READ_ONLY_ENDPOINTS = (
    "/product/list",
    "/product/query",
    "/product/stock/queryByVid",
    "/product/stock/queryBySku",
)


@dataclass(frozen=True)
class CjReadOnlyConfig:
    provider: str
    live_flag_enabled: bool
    credentials_present: bool
    allow_network: bool = False

    @property
    def configured(self) -> bool:
        return self.provider == PROVIDER and self.credentials_present

    def to_dict(self) -> dict[str, Any]:
        if not self.configured:
            status = "provider_mismatch" if self.provider != PROVIDER else "credential_missing"
        elif not self.live_flag_enabled:
            status = "live_flag_disabled"
        elif not self.allow_network:
            status = "network_gate_required"
        else:
            status = "ready"
        return {
            "provider": self.provider,
            "credentials_present_redacted": self.credentials_present,
            "live_flag_enabled": self.live_flag_enabled,
            "allow_network": self.allow_network,
            "configured": self.configured,
            "status": status,
            "endpoints": list(READ_ONLY_ENDPOINTS),
            "read_only": True,
            "mutated": False,
            "forbidden_actions": ["create_order", "capture_payment", "refund", "fulfill", "mutate_inventory", "publish_product"],
        }


def cj_read_only_config(environ: Mapping[str, str] | None = None, *, allow_network: bool = False) -> CjReadOnlyConfig:
    env = os.environ if environ is None else environ
    return CjReadOnlyConfig(
        provider=str(env.get(PROVIDER_ENV, "cj")).strip().lower() or "cj",
        live_flag_enabled=str(env.get(LIVE_FLAG, "0")).strip() == "1",
        credentials_present=bool(str(env.get("CJ_EMAIL", "")).strip() and str(env.get("CJ_API_KEY", "")).strip()),
        allow_network=allow_network,
    )


def explain_cj_read_only_readiness(environ: Mapping[str, str] | None = None, *, allow_network: bool = False) -> dict[str, Any]:
    return cj_read_only_config(environ, allow_network=allow_network).to_dict()


@dataclass(frozen=True)
class CjReadOnlyResult:
    status: str
    provider: str = PROVIDER
    source_type: str = "authenticated_readonly_api"
    products: tuple[CJProductEvidence, ...] = ()
    warnings: tuple[str, ...] = ()
    endpoint_statuses: dict[str, str] = field(default_factory=dict)
    attempted: bool = False

    @property
    def best(self) -> CJProductEvidence | None:
        priced = [item for item in self.products if item.price is not None and item.field_status.get("price") == "observed"]
        return priced[0] if priced else (self.products[0] if self.products else None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "provider": self.provider,
            "source_type": self.source_type,
            "products": [item.to_dict() for item in self.products],
            "warnings": list(self.warnings),
            "endpoint_statuses": dict(sorted(self.endpoint_statuses.items())),
            "attempted": self.attempted,
            "read_only": True,
            "mutated": False,
        }


def _value(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if row.get(key) not in (None, ""):
            return row[key]
    return None


def _number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _rows(payload: Mapping[str, Any], key: str = "list") -> list[dict[str, Any]]:
    data = payload.get("data", payload)
    if isinstance(data, Mapping):
        data = data.get(key, data.get("records", []))
    return [dict(item) for item in data if isinstance(item, Mapping)] if isinstance(data, list) else []


def normalize_cj_product(product: Mapping[str, Any], *, detail: Mapping[str, Any] | None = None, stock: list[Mapping[str, Any]] | None = None, observed_at: float = 0.0) -> CJProductEvidence:
    row = dict(product)
    if detail:
        row.update({key: value for key, value in detail.items() if value not in (None, "", [], {})})
    pid = str(_value(row, "pid", "productId", "id") or "unavailable")
    title = str(_value(row, "productNameEn", "nameEn", "productName", "name") or "")
    price = _number(_value(row, "sellPrice", "price", "cost"))
    sku = str(_value(row, "productSku", "sku", "productCode") or "")
    raw_variants = _value(row, "variants", "variantList")
    variants: list[dict[str, Any]] = []
    if isinstance(raw_variants, list):
        for variant in raw_variants:
            if not isinstance(variant, Mapping):
                continue
            variants.append({
                "variant_id": str(_value(variant, "vid", "variantId", "id") or ""),
                "sku": str(_value(variant, "variantSku", "sku") or ""),
                "name": str(_value(variant, "variantNameEn", "variantName", "name") or ""),
                "price": _number(_value(variant, "sellPrice", "price")),
            })
    stock_rows = [dict(item) for item in (stock or []) if isinstance(item, Mapping)]
    quantities = [_int(_value(item, "storageNum", "totalInventoryNum", "cjInventoryNum", "inventory", "quantity")) for item in stock_rows]
    quantities = [item for item in quantities if item is not None]
    inventory_quantity = sum(quantities) if quantities else None
    field_status = {name: "unavailable" for name in (
        "title", "price", "sku", "category", "variants", "weight_kg", "inventory_status", "inventory_quantity",
        "warehouse_origin", "shipping_cost", "estimated_delivery_days", "quality_evidence", "rating", "reviews_count", "images", "description",
    )}
    if title: field_status["title"] = "observed"
    if price is not None: field_status["price"] = "observed"
    if sku: field_status["sku"] = "observed"
    if variants: field_status["variants"] = "observed"
    if stock_rows:
        field_status["inventory_status"] = "observed"
    if inventory_quantity is not None:
        field_status["inventory_quantity"] = "observed"
    status = "in_stock" if inventory_quantity and inventory_quantity > 0 else "out_of_stock" if inventory_quantity == 0 else "unavailable"
    confidence = round(sum(value == "observed" for value in field_status.values()) / len(field_status), 3)
    warnings = () if price is not None else ("supplier_price_unavailable",)
    return CJProductEvidence(
        source=SOURCE, source_url="https://developers.cjdropshipping.com/api2.0/v1/product/query",
        observed_at=observed_at, external_product_id=pid, title=title, field_status=field_status,
        sku=sku, price=price, currency=str(_value(row, "currency", "currencyCode") or "USD"), variants=tuple(variants),
        inventory_status=status, inventory_quantity=inventory_quantity, warehouse_origin=str(_value(row, "warehouse", "warehouseName") or ""),
        weight_kg=_number(_value(row, "weight", "weightKg")), shipping_cost=None,
        estimated_delivery_days=None, images=tuple(str(item) for item in (_value(row, "imageList", "images") or []) if item),
        description=str(_value(row, "description") or ""), extraction_method="cj_readonly_api",
        confidence=confidence, warnings=warnings,
    )


class CjReadOnlySupplierAdapter:
    def __init__(self, client: CJDropshippingClient | None = None, *, clock: Any = time.time):
        self.client = client or CJDropshippingClient()
        self.clock = clock

    def search(self, query: str, *, limit: int = 5, allow_network: bool = False) -> CjReadOnlyResult:
        config = cj_read_only_config(allow_network=allow_network)
        if config.provider != PROVIDER:
            return CjReadOnlyResult("provider_mismatch", warnings=("MARKETOS_SUPPLIER_PROVIDER must be cj",))
        if not config.credentials_present:
            return CjReadOnlyResult("credential_missing", warnings=("CJ_EMAIL and CJ_API_KEY are required; secret values were not inspected",))
        if not config.live_flag_enabled:
            return CjReadOnlyResult("live_flag_disabled", warnings=(f"{LIVE_FLAG}=1 is required",))
        if not allow_network:
            return CjReadOnlyResult("network_gate_required", warnings=("--allow-network is required for authenticated supplier reads",))
        bounded_limit = max(1, min(int(limit), 10))
        statuses: dict[str, str] = {}
        try:
            listing = self.client.read_only_get("/product/list", params={"pageNum": 1, "pageSize": bounded_limit, "productNameEn": query.strip()})
            statuses["/product/list"] = "success"
            products: list[CJProductEvidence] = []
            for row in _rows(listing)[:bounded_limit]:
                pid = _value(row, "pid", "productId", "id")
                if not pid:
                    continue
                detail_payload = self.client.read_only_get("/product/query", params={"pid": str(pid)})
                statuses["/product/query"] = "success"
                detail_rows = _rows(detail_payload, key="data")
                detail = detail_rows[0] if detail_rows else (detail_payload.get("data") if isinstance(detail_payload.get("data"), Mapping) else {})
                detail = detail if isinstance(detail, Mapping) else {}
                variant_rows = _value(detail, "variants", "variantList") or _value(row, "variants", "variantList") or []
                stock_rows: list[Mapping[str, Any]] = []
                for variant in variant_rows if isinstance(variant_rows, list) else []:
                    vid = _value(variant, "vid", "variantId", "id") if isinstance(variant, Mapping) else None
                    if not vid:
                        continue
                    stock_payload = self.client.read_only_get("/product/stock/queryByVid", params={"vid": str(vid)})
                    statuses["/product/stock/queryByVid"] = "success"
                    stock_rows.extend(_rows(stock_payload, key="data"))
                products.append(normalize_cj_product(row, detail=detail, stock=stock_rows, observed_at=self.clock()))
            return CjReadOnlyResult("observed" if products else "no_results", products=tuple(products), endpoint_statuses=statuses, attempted=True)
        except Exception as exc:  # noqa: BLE001 - provider boundary returns structured status
            return CjReadOnlyResult("provider_failed", warnings=(f"provider_request_failed:{type(exc).__name__}",), endpoint_statuses=statuses, attempted=True)


__all__ = ["CjReadOnlyConfig", "CjReadOnlyResult", "CjReadOnlySupplierAdapter", "cj_read_only_config", "explain_cj_read_only_readiness", "normalize_cj_product", "READ_ONLY_ENDPOINTS"]
