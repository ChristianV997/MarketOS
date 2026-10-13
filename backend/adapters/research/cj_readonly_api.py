"""Explicitly gated, read-only CJ catalog evidence adapter.

The adapter reuses ``CJDropshippingClient``'s existing token exchange and
restricts calls to the documented product/list, product/query, and stock GET
endpoints. It never exposes or stores credentials and never reaches order,
payment, logistics-write, or fulfillment operations.
"""
from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field
from typing import Any, Mapping

from backend.adapters.research.cj_public_evidence import CJProductEvidence
from backend.validation.suppliers import CJDropshippingClient
from evaluation.commerce.supplier_feasibility import integer, normalize_delivery_window

SOURCE = "cj_authenticated_api"
PROVIDER = "cj"
LIVE_FLAG = "MARKETOS_SUPPLIER_AUTH_READONLY"
PROVIDER_ENV = "MARKETOS_SUPPLIER_PROVIDER"
READ_ONLY_ENDPOINTS = (
    "/product/listV2",
    "/product/list",
    "/product/query",
    "/product/stock/queryByVid",
    "/product/stock/queryBySku",
)
READ_ONLY_POST_ENDPOINTS = ("/logistic/freightCalculate",)


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
            "post_endpoints": list(READ_ONLY_POST_ENDPOINTS),
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
class CjReadOnlyOffer:
    """Sanitized catalog, destination-inventory, and freight facts for a variant."""

    product: CJProductEvidence
    product_id: str
    variant_id: str
    supplier_sku: str
    supplier_title: str
    unit_cost: float | None
    currency: str | None
    minimum_order_quantity: int | None
    product_type: str
    fulfillment_method: str
    destination_inventory_quantity: int | None
    destination_inventory_status: str
    warehouse_region: str
    source_country_code: str
    shipping_quotes: tuple[dict[str, Any], ...]
    field_provenance: dict[str, str] = field(default_factory=dict)
    field_timestamps: dict[str, float | None] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "product": self.product.to_dict(),
            "product_id": self.product_id,
            "variant_id": self.variant_id,
            "supplier_sku": self.supplier_sku,
            "supplier_title": self.supplier_title,
            "unit_cost": self.unit_cost,
            "currency": self.currency,
            "minimum_order_quantity": self.minimum_order_quantity,
            "product_type": self.product_type,
            "fulfillment_method": self.fulfillment_method,
            "destination_inventory_quantity": self.destination_inventory_quantity,
            "destination_inventory_status": self.destination_inventory_status,
            "warehouse_region": self.warehouse_region,
            "source_country_code": self.source_country_code,
            "shipping_quotes": [dict(quote) for quote in self.shipping_quotes],
            "field_provenance": dict(self.field_provenance),
            "field_timestamps": dict(self.field_timestamps),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class CjReadOnlyResult:
    status: str
    provider: str = PROVIDER
    source_type: str = "authenticated_readonly_api"
    products: tuple[CJProductEvidence, ...] = ()
    warnings: tuple[str, ...] = ()
    endpoint_statuses: dict[str, str] = field(default_factory=dict)
    attempted: bool = False
    offers: tuple[CjReadOnlyOffer, ...] = ()

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
            "offers": [item.to_dict() for item in self.offers],
            "read_only": True,
            "mutated": False,
        }


def _value(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if row.get(key) not in (None, ""):
            return row[key]
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None
    return result if result is not None and math.isfinite(result) and result >= 0 else None


def _int(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None and number.is_integer() else None


def _rows(payload: Mapping[str, Any], key: str = "list") -> list[dict[str, Any]]:
    data = payload.get("data", payload)
    if isinstance(data, Mapping):
        data = data.get(key, data.get("records", []))
    return [dict(item) for item in data if isinstance(item, Mapping)] if isinstance(data, list) else []


def _product_list_v2_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data", payload)
    content = data.get("content", []) if isinstance(data, Mapping) else []
    products: list[dict[str, Any]] = []
    if isinstance(content, list):
        for group in content:
            rows = group.get("productList", []) if isinstance(group, Mapping) else []
            products.extend(dict(row) for row in rows if isinstance(row, Mapping))
    return products


def _api_success(payload: Mapping[str, Any]) -> bool:
    return payload.get("code") in (None, 200, "200") and payload.get("result") is not False


def _country_code(row: Mapping[str, Any]) -> str:
    return str(_value(row, "countryCode", "country_code") or "").strip().upper()


def _stock_quantity(row: Mapping[str, Any]) -> int | None:
    return integer(_value(row, "storageNum", "cjInventoryNum"))


def normalize_cj_product(
    product: Mapping[str, Any],
    *,
    detail: Mapping[str, Any] | None = None,
    stock: list[Mapping[str, Any]] | None = None,
    observed_at: float = 0.0,
    source: str = SOURCE,
) -> CJProductEvidence:
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
        "title", "price", "currency", "sku", "category", "variants", "weight_kg", "inventory_status", "inventory_quantity",
        "warehouse_origin", "shipping_cost", "estimated_delivery_days", "quality_evidence", "rating", "reviews_count", "images", "description",
    )}
    if title: field_status["title"] = "observed"
    if price is not None: field_status["price"] = "observed"
    raw_currency = _value(row, "currency", "currencyCode")
    currency = str(raw_currency).strip().upper() if raw_currency not in (None, "") else ("USD" if price is not None else None)
    if raw_currency not in (None, ""):
        field_status["currency"] = "observed"
    elif currency is not None:
        field_status["currency"] = "derived"
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
        source=source, source_url="https://developers.cjdropshipping.com/api2.0/v1/product/query",
        observed_at=observed_at, external_product_id=pid, title=title, field_status=field_status,
        sku=sku, price=price, currency=currency, variants=tuple(variants),
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

    def search_fixture(
        self,
        query: str,
        *,
        destination_country_code: str,
        postal_code: str | None = None,
        limit: int = 5,
    ) -> CjReadOnlyResult:
        """Run the current CJ read-only flow against an injected offline transport.

        Unlike ``search``, this path never uses the default HTTP client or a
        provider credential. Its outputs are always classified as fixtures.
        """
        destination = str(destination_country_code).strip().upper()
        if not query.strip():
            return CjReadOnlyResult("invalid_query", source_type="cj_readonly_fixture", warnings=("candidate_search_terms_missing",))
        if len(destination) != 2 or not destination.isascii() or not destination.isalpha():
            return CjReadOnlyResult("invalid_destination", source_type="cj_readonly_fixture", warnings=("destination_country_code_invalid",))
        if isinstance(self.client, CJDropshippingClient):
            return CjReadOnlyResult(
                "fixture_transport_required",
                source_type="cj_readonly_fixture",
                warnings=("fixture_search_requires_injected_transport",),
            )

        bounded_limit = max(1, min(int(limit), 10))
        statuses: dict[str, str] = {}
        try:
            listing = self.client.read_only_get(
                "/product/listV2",
                params={"page": 1, "size": bounded_limit, "keyWord": query.strip()},
            )
            if not isinstance(listing, Mapping) or not _api_success(listing):
                return CjReadOnlyResult(
                    "fixture_failed",
                    source_type="cj_readonly_fixture",
                    warnings=("product_search_response_unavailable",),
                    endpoint_statuses={"/product/listV2": "failed"},
                )
            statuses["/product/listV2"] = "success"
            catalog_at = float(self.clock())
            products: list[CJProductEvidence] = []
            offers: list[CjReadOnlyOffer] = []
            for row in _product_list_v2_rows(listing)[:bounded_limit]:
                product_id_value = _value(row, "pid", "productId", "id")
                if not product_id_value:
                    continue
                product_id = str(product_id_value)
                detail_payload = self.client.read_only_get("/product/query", params={"pid": product_id})
                if not isinstance(detail_payload, Mapping) or not _api_success(detail_payload):
                    statuses["/product/query"] = "failed"
                    continue
                statuses["/product/query"] = "success"
                detail_value = detail_payload.get("data")
                detail = detail_value if isinstance(detail_value, Mapping) else {}
                detail_at = float(self.clock())
                variants_value = _value(detail, "variants", "variantList") or _value(row, "variants", "variantList") or []
                variants = [item for item in variants_value if isinstance(item, Mapping)] if isinstance(variants_value, list) else []
                if not variants:
                    variants = [{}]

                pending: list[dict[str, Any]] = []
                product_stock_rows: list[Mapping[str, Any]] = []
                for variant in variants[:3]:
                    variant_id = str(_value(variant, "vid", "variantId", "id") or "")
                    variant_sku = str(
                        _value(variant, "variantSku", "sku")
                        or _value(detail, "productSku", "sku")
                        or _value(row, "sku", "productSku")
                        or ""
                    )
                    variant_price_value = _value(variant, "variantSellPrice", "sellPrice", "price")
                    detail_price_value = _value(detail, "sellPrice", "price")
                    listing_price_value = _value(row, "sellPrice", "price")
                    unit_cost = _number(variant_price_value)
                    if unit_cost is None:
                        unit_cost = _number(detail_price_value or listing_price_value)
                    unit_cost_at = detail_at if variant_price_value not in (None, "") or detail_price_value not in (None, "") else catalog_at if listing_price_value not in (None, "") else None
                    variant_currency = _value(variant, "currency", "currencyCode")
                    detail_currency = _value(detail, "currency", "currencyCode")
                    listing_currency = _value(row, "currency", "currencyCode")
                    currency_value = variant_currency or detail_currency or listing_currency
                    currency_at = detail_at if variant_currency or detail_currency else catalog_at if listing_currency else unit_cost_at
                    currency = (
                        str(currency_value).strip().upper()
                        if currency_value not in (None, "")
                        else "USD" if unit_cost is not None else None
                    )
                    currency_provenance = "fixture" if currency_value not in (None, "") else "derived" if currency else "unavailable"
                    detail_moq = _value(detail, "directMinOrderNum", "minimumOrderQuantity")
                    listing_moq = _value(row, "directMinOrderNum", "minimumOrderQuantity")
                    moq = integer(detail_moq or listing_moq)
                    moq_at = detail_at if detail_moq not in (None, "") else catalog_at if listing_moq not in (None, "") else None
                    detail_type = _value(detail, "productType", "productTypeCode")
                    listing_type = _value(row, "productType", "productTypeCode")
                    product_type = str(detail_type or listing_type or "")
                    product_type_at = detail_at if detail_type not in (None, "") else catalog_at if listing_type not in (None, "") else None
                    title_at = detail_at if _value(detail, "productNameEn", "nameEn", "productName", "name") else catalog_at
                    sku_at = detail_at if _value(variant, "variantSku", "sku") or _value(detail, "productSku", "sku") else catalog_at
                    stock_rows: list[dict[str, Any]] = []
                    stock_at: float | None = None
                    if variant_id:
                        stock_payload = self.client.read_only_get("/product/stock/queryByVid", params={"vid": variant_id})
                        if not isinstance(stock_payload, Mapping) or not _api_success(stock_payload):
                            statuses["/product/stock/queryByVid"] = "failed"
                        else:
                            statuses["/product/stock/queryByVid"] = "success"
                            stock_rows = _rows(stock_payload, key="data")
                            product_stock_rows.extend(stock_rows)
                            stock_at = float(self.clock())

                    destination_rows = [item for item in stock_rows if _country_code(item) == destination]
                    destination_quantities = [_stock_quantity(item) for item in destination_rows]
                    destination_quantities = [item for item in destination_quantities if item is not None]
                    destination_quantity = sum(destination_quantities) if destination_quantities else None
                    destination_status = (
                        "in_stock" if destination_quantity is not None and destination_quantity > 0
                        else "out_of_stock" if destination_quantity == 0
                        else "unknown"
                    )
                    origin_rows: list[tuple[bool, str, str, Mapping[str, Any]]] = []
                    for item in stock_rows:
                        country = _country_code(item)
                        quantity = _stock_quantity(item)
                        if country and quantity is not None and quantity > 0:
                            origin_rows.append((country != destination, country, str(_value(item, "areaId") or ""), item))
                    origin_rows.sort(key=lambda entry: (entry[0], entry[1], entry[2]))
                    selected_origin = origin_rows[0][3] if origin_rows else None
                    origin_country = _country_code(selected_origin or {})
                    warehouse = str(_value(selected_origin or {}, "areaEn", "warehouse", "warehouseName") or "")
                    warnings: list[str] = []
                    quotes: list[dict[str, Any]] = []
                    quote_at: float | None = None
                    if variant_id and origin_country:
                        body: dict[str, Any] = {
                            "startCountryCode": origin_country,
                            "endCountryCode": destination,
                            "products": [{"vid": variant_id, "quantity": 1}],
                        }
                        if postal_code:
                            body["zip"] = str(postal_code).strip()[:20]
                        freight = self.client.read_only_post("/logistic/freightCalculate", json_body=body)
                        if not isinstance(freight, Mapping) or not _api_success(freight):
                            statuses["/logistic/freightCalculate"] = "failed"
                            warnings.append("destination_freight_quote_unavailable")
                        else:
                            statuses["/logistic/freightCalculate"] = "success"
                            quote_rows = freight.get("data", [])
                            quote_at = float(self.clock())
                            if isinstance(quote_rows, list):
                                for quote_row in quote_rows:
                                    if not isinstance(quote_row, Mapping):
                                        continue
                                    min_days, max_days = normalize_delivery_window(_value(quote_row, "logisticAging"))
                                    cost_usd = _number(_value(quote_row, "logisticPrice"))
                                    cost_cny = _number(_value(quote_row, "logisticPriceCn"))
                                    quote_provenance = {
                                        "shipping_cost_usd": "fixture" if cost_usd is not None else "unavailable",
                                        "shipping_cost_cny": "fixture" if cost_cny is not None else "unavailable",
                                        "delivery_min_days": "fixture" if min_days is not None else "unavailable",
                                        "delivery_max_days": "fixture" if max_days is not None else "unavailable",
                                        "logistic_name": "fixture" if _value(quote_row, "logisticName") else "unavailable",
                                    }
                                    quotes.append({
                                        "origin_country_code": origin_country,
                                        "destination_country_code": destination,
                                        "logistic_name": str(_value(quote_row, "logisticName") or ""),
                                        "shipping_cost_usd": cost_usd,
                                        "shipping_cost_cny": cost_cny,
                                        "delivery_min_days": min_days,
                                        "delivery_max_days": max_days,
                                        "quote_quantity": 1,
                                        "captured_at": quote_at,
                                        "field_provenance": quote_provenance,
                                    })
                            if not quotes:
                                warnings.append("destination_freight_quote_unavailable")
                    elif variant_id:
                        warnings.append("no_stock_origin_for_freight_quote")
                    if quotes and moq is not None and moq > 1:
                        warnings.append("freight_quote_quantity_one_below_moq")

                    pending.append({
                        "variant_id": variant_id,
                        "supplier_sku": variant_sku,
                        "unit_cost": unit_cost,
                        "unit_cost_at": unit_cost_at,
                        "currency": currency,
                        "currency_at": currency_at,
                        "currency_provenance": currency_provenance,
                        "moq": moq,
                        "moq_at": moq_at,
                        "product_type": product_type,
                        "product_type_at": product_type_at,
                        "title_at": title_at,
                        "sku_at": sku_at,
                        "fulfillment_method": "supplier_shipped" if product_type == "SUPPLIER_SHIPPED_PRODUCT" else "",
                        "destination_quantity": destination_quantity,
                        "destination_status": destination_status,
                        "warehouse": warehouse,
                        "source_country": origin_country,
                        "stock_at": stock_at,
                        "quotes": tuple(quotes),
                        "quote_at": quote_at,
                        "warnings": tuple(warnings),
                    })

                product_keys = {
                    "pid", "id", "productId", "productNameEn", "nameEn", "productName", "name",
                    "productSku", "sku", "sellPrice", "price", "currency", "currencyCode", "productType",
                    "productTypeCode", "directMinOrderNum", "minimumOrderQuantity", "weight", "weightKg",
                    "variants", "variantList",
                }
                variant_keys = {
                    "vid", "variantId", "id", "variantSku", "sku", "variantNameEn", "variantName",
                    "name", "variantSellPrice", "sellPrice", "price", "currency", "currencyCode",
                }
                safe_row = {key: row[key] for key in product_keys if key in row}
                safe_detail = {key: detail[key] for key in product_keys if key in detail}
                for source_row in (safe_row, safe_detail):
                    for variants_key in ("variants", "variantList"):
                        variants_value = source_row.get(variants_key)
                        if isinstance(variants_value, list):
                            source_row[variants_key] = [
                                {key: value for key, value in item.items() if key in variant_keys}
                                for item in variants_value
                                if isinstance(item, Mapping)
                            ]
                safe_stock_rows: list[Mapping[str, Any]] = [
                    {key: value for key, value in item.items() if key in {"vid", "areaId", "areaEn", "countryCode", "storageNum", "totalInventoryNum", "cjInventoryNum", "factoryInventoryNum"}}
                    for item in product_stock_rows
                ]
                product_evidence = normalize_cj_product(
                    safe_row,
                    detail=safe_detail,
                    stock=safe_stock_rows,
                    observed_at=detail_at,
                    source="cj_readonly_fixture",
                )
                products.append(product_evidence)
                for item in pending:
                    quote_values = item["quotes"]
                    has_shipping = any(
                        quote.get("shipping_cost_usd") is not None or quote.get("shipping_cost_cny") is not None
                        for quote in quote_values
                    )
                    field_provenance = {
                        "supplier_product_id": "fixture",
                        "supplier_title": "fixture" if product_evidence.title else "unavailable",
                        "supplier_sku": "fixture" if item["supplier_sku"] else "unavailable",
                        "unit_cost": "fixture" if item["unit_cost"] is not None else "unavailable",
                        "currency": item["currency_provenance"],
                        "moq": "fixture" if item["moq"] is not None else "unavailable",
                        "inventory_status": "fixture" if item["destination_quantity"] is not None else "unavailable",
                        "inventory_quantity": "fixture" if item["destination_quantity"] is not None else "unavailable",
                        "warehouse_region": "fixture" if item["warehouse"] else "unavailable",
                        "destination_region": "derived",
                        "fulfillment_method": "fixture" if item["fulfillment_method"] else "unavailable",
                        "supplier_rating": "unavailable",
                        "supplier_review_count": "unavailable",
                        "shipping_cost": "fixture" if has_shipping else "unavailable",
                        "shipping_currency": "derived" if has_shipping else "unavailable",
                        "delivery_min_days": "fixture" if quote_values and quote_values[0].get("delivery_min_days") is not None else "unavailable",
                        "delivery_max_days": "fixture" if quote_values and quote_values[0].get("delivery_max_days") is not None else "unavailable",
                    }
                    field_timestamps = {
                        "supplier_product_id": catalog_at,
                        "supplier_title": item["title_at"],
                        "supplier_sku": item["sku_at"],
                        "unit_cost": item["unit_cost_at"],
                        "currency": item["currency_at"],
                        "moq": item["moq_at"],
                        "inventory_status": item["stock_at"],
                        "inventory_quantity": item["stock_at"],
                        "warehouse_region": item["stock_at"],
                        "destination_region": item["stock_at"],
                        "fulfillment_method": item["product_type_at"],
                        "shipping_cost": item["quote_at"],
                        "shipping_currency": item["quote_at"],
                        "delivery_min_days": item["quote_at"],
                        "delivery_max_days": item["quote_at"],
                    }
                    offers.append(CjReadOnlyOffer(
                        product=product_evidence,
                        product_id=product_id,
                        variant_id=item["variant_id"],
                        supplier_sku=item["supplier_sku"],
                        supplier_title=product_evidence.title,
                        unit_cost=item["unit_cost"],
                        currency=item["currency"],
                        minimum_order_quantity=item["moq"],
                        product_type=item["product_type"],
                        fulfillment_method=item["fulfillment_method"],
                        destination_inventory_quantity=item["destination_quantity"],
                        destination_inventory_status=item["destination_status"],
                        warehouse_region=item["warehouse"],
                        source_country_code=item["source_country"],
                        shipping_quotes=quote_values,
                        field_provenance=field_provenance,
                        field_timestamps=field_timestamps,
                        warnings=item["warnings"],
                    ))
            return CjReadOnlyResult(
                "fixture" if offers else "no_results",
                source_type="cj_readonly_fixture",
                products=tuple(products),
                endpoint_statuses=statuses,
                attempted=False,
                offers=tuple(offers),
            )
        except Exception as exc:  # noqa: BLE001 - fixture transport boundary is fail-soft
            return CjReadOnlyResult(
                "fixture_failed",
                source_type="cj_readonly_fixture",
                warnings=(f"fixture_transport_failed:{type(exc).__name__}",),
                endpoint_statuses=statuses,
                attempted=False,
            )



__all__ = [
    "CjReadOnlyConfig",
    "CjReadOnlyOffer",
    "CjReadOnlyResult",
    "CjReadOnlySupplierAdapter",
    "READ_ONLY_ENDPOINTS",
    "READ_ONLY_POST_ENDPOINTS",
    "cj_read_only_config",
    "explain_cj_read_only_readiness",
    "normalize_cj_product",
]
