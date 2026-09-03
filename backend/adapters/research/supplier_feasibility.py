"""Sanitized offline supplier-feasibility importers.

This adapter intentionally has no HTTP client. It turns local CJ validation-pack
fixtures and seller-provided CSV snapshots into the shared feasibility model.
"""
from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any, Mapping

from evaluation.commerce.supplier_feasibility import (
    PROVENANCE,
    SOURCE_TYPES,
    SUPPLIERS,
    SupplierFeasibilityEvidence,
    collapse_duplicates,
    integer,
    normalize_delivery_window,
    normalize_inventory_status,
    number,
)

SECRET_KEY = re.compile(r"(token|secret|password|api[_-]?key|authorization|cookie|private[_-]?key)", re.I)
SECRET_VALUE = re.compile(r"(bearer\s+|sk_live_|sk_test_|ghp_|xox[baprs]-|-----BEGIN)", re.I)
HTML_MARKERS = re.compile(r"<(?:!DOCTYPE\s+html|html|body|script)\b", re.I)


class SupplierImportError(ValueError):
    pass


def validate_input_path(path: str | Path) -> Path:
    candidate = Path(path)
    if ".." in candidate.parts:
        raise SupplierImportError("path traversal is not allowed")
    if candidate.suffix.lower() not in {".json", ".csv"}:
        raise SupplierImportError("only sanitized JSON and CSV inputs are supported")
    if not candidate.is_file():
        raise SupplierImportError("supplier import file does not exist")
    return candidate


def contains_secret(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(SECRET_KEY.search(str(key)) or contains_secret(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(contains_secret(item) for item in value)
    return bool(SECRET_VALUE.search(str(value))) if value is not None else False


def contains_html(value: Any) -> bool:
    """Detect raw HTML document/script markers. A lone '<' is not HTML."""
    if isinstance(value, Mapping):
        return any(contains_html(key) or contains_html(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(contains_html(item) for item in value)
    if value is None:
        return False
    if isinstance(value, (bytes, bytearray, memoryview)):
        text = bytes(value).decode("utf-8", errors="replace")
    else:
        text = str(value)
    return bool(HTML_MARKERS.search(text))


def _reject_raw_html(value: Any) -> None:
    if contains_html(value):
        raise SupplierImportError("raw HTML is not allowed")


def _read_import_text(path: str | Path, *, encoding: str = "utf-8") -> str:
    target = validate_input_path(path)
    raw_bytes = target.read_bytes()
    _reject_raw_html(raw_bytes)
    text = raw_bytes.decode(encoding)
    _reject_raw_html(text)
    return text


def _clean(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _clean(item) for key, item in value.items() if not SECRET_KEY.search(str(key))}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    return value


def _value(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if row.get(name) not in (None, ""):
            return row[name]
    return None


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "best_seller", "bestseller"}


def _fallback_provenance(mode: str) -> str:
    return "manual_import" if mode == "manual_import" else "fixture"


def _provenance(row: Mapping[str, Any], mode: str) -> dict[str, str]:
    raw = row.get("field_provenance")
    result = {}
    if isinstance(raw, Mapping):
        result = {str(key): str(value) if str(value) in PROVENANCE else "malformed" for key, value in raw.items()}
    fallback = _fallback_provenance(mode)
    fields = (
        "supplier_product_id", "supplier_title", "supplier_sku", "variant_count", "moq", "unit_cost", "shipping_cost",
        "estimated_landed_cost", "delivery_min_days", "delivery_max_days", "inventory_status", "inventory_quantity",
        "warehouse_region", "destination_region", "fulfillment_method", "supplier_rating", "supplier_review_count",
        "order_count_text", "best_seller_badge", "trend_label", "return_policy_signal", "refund_policy_signal",
    )
    for field_name in fields:
        if field_name not in result and row.get(field_name) not in (None, ""):
            result[field_name] = fallback
    if row.get("estimated_landed_cost") in (None, "") and row.get("unit_cost") not in (None, "") and row.get("shipping_cost") not in (None, ""):
        result["estimated_landed_cost"] = "derived"
    return result


def normalize_record(
    row: Mapping[str, Any],
    *,
    default_supplier: str = "cj",
    default_source_type: str = "fixture_demo",
    mode: str = "fixture",
) -> SupplierFeasibilityEvidence | None:
    if not isinstance(row, Mapping):
        return None
    _reject_raw_html(row)
    if contains_secret(row):
        return None
    row = _clean(row)
    nested = row.get("product") if isinstance(row.get("product"), Mapping) else {}
    merged = {**nested, **row}
    supplier = str(_value(merged, "supplier", "provider") or default_supplier).lower()
    if supplier not in SUPPLIERS:
        return None
    source_type = str(_value(merged, "source_type") or default_source_type)
    if source_type not in SOURCE_TYPES:
        source_type = default_source_type if default_source_type in SOURCE_TYPES else "fixture_demo"
    candidate_id = str(_value(merged, "candidate_id", "product_id", "supplier_product_id") or "").strip()
    if not candidate_id:
        return None
    delivery_min = integer(_value(merged, "delivery_min_days", "min_delivery_days"))
    delivery_max = integer(_value(merged, "delivery_max_days", "max_delivery_days"))
    if delivery_min is None or delivery_max is None:
        parsed_min, parsed_max = normalize_delivery_window(_value(merged, "delivery_window", "estimated_delivery", "shipping_time"))
        delivery_min = delivery_min if delivery_min is not None else parsed_min
        delivery_max = delivery_max if delivery_max is not None else parsed_max
    unit_cost = number(_value(merged, "unit_cost", "supplier_price", "price", "cost"))
    shipping_cost = number(_value(merged, "shipping_cost", "shipping", "freight_cost"))
    landed = number(_value(merged, "estimated_landed_cost", "landed_cost"))
    warnings = [str(item) for item in merged.get("warnings", []) if isinstance(item, str)]
    if landed is None and unit_cost is not None and shipping_cost is not None:
        landed = unit_cost + shipping_cost
    if unit_cost is None:
        warnings.append("unit_cost_unavailable")
    if shipping_cost is None:
        warnings.append("shipping_cost_unavailable")
    quantity = integer(_value(merged, "inventory_quantity", "stock", "inventory"))
    inventory = normalize_inventory_status(_value(merged, "inventory_status", "stock_status", "availability"), quantity)
    raw_evidence_mode = _value(merged, "evidence_mode")
    evidence_mode = str(raw_evidence_mode) if raw_evidence_mode is not None else mode
    observed = _value(merged, "observed_at", "captured_at")
    return SupplierFeasibilityEvidence(
        candidate_id=candidate_id,
        query=str(_value(merged, "query", "supplier_title", "title") or candidate_id),
        supplier=supplier,
        source_type=source_type,
        source_url=str(_value(merged, "source_url", "url") or ""),
        evidence_mode=evidence_mode,
        supplier_product_id=str(_value(merged, "supplier_product_id", "product_id", "item_id") or ""),
        supplier_title=str(_value(merged, "supplier_title", "title", "product_title") or ""),
        supplier_brand=str(_value(merged, "supplier_brand", "brand") or ""),
        supplier_sku=str(_value(merged, "supplier_sku", "sku", "variant_sku") or ""),
        variant_count=integer(_value(merged, "variant_count", "variants")),
        moq=integer(_value(merged, "moq", "minimum_order_quantity", "minimum_quantity")),
        unit_cost=unit_cost,
        currency=str(_value(merged, "currency", "price_currency") or "USD").upper(),
        shipping_cost=shipping_cost,
        estimated_landed_cost=landed,
        delivery_min_days=delivery_min,
        delivery_max_days=delivery_max,
        inventory_status=inventory,
        inventory_quantity=quantity,
        warehouse_region=str(_value(merged, "warehouse_region", "warehouse", "origin") or ""),
        destination_region=str(_value(merged, "destination_region", "destination") or ""),
        fulfillment_method=str(_value(merged, "fulfillment_method", "fulfillment") or ""),
        supplier_rating=number(_value(merged, "supplier_rating", "rating")),
        supplier_review_count=integer(_value(merged, "supplier_review_count", "review_count", "reviews")),
        order_count_text=str(_value(merged, "order_count_text", "order_count", "orders") or ""),
        best_seller_badge=_bool(_value(merged, "best_seller_badge", "best_seller")),
        trend_label=str(_value(merged, "trend_label", "trend") or ""),
        return_policy_signal=str(_value(merged, "return_policy_signal", "return_policy") or ""),
        refund_policy_signal=str(_value(merged, "refund_policy_signal", "refund_policy") or ""),
        source_confidence=max(0.0, min(1.0, number(_value(merged, "source_confidence", "confidence")) or (0.7 if mode == "manual_import" else 0.55))),
        field_provenance=_provenance(merged, mode),
        warnings=tuple(sorted(set(warnings))),
        observed_at="" if observed is None else str(observed),
    )


def _rows_from_json(path: str | Path) -> list[Mapping[str, Any]]:
    raw = json.loads(_read_import_text(path))
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, Mapping)]
    if isinstance(raw, Mapping):
        for key in ("records", "items", "products", "offers", "supplier_evidence", "candidates"):
            if isinstance(raw.get(key), list):
                return [item for item in raw[key] if isinstance(item, Mapping)]
        if isinstance(raw.get("supplier_evidence"), Mapping):
            return [raw["supplier_evidence"]]
        return [raw]
    return []


def import_json(path: str | Path, *, supplier: str = "cj", source_type: str = "fixture_demo") -> list[SupplierFeasibilityEvidence]:
    rows = _rows_from_json(path)
    return collapse_duplicates(item for row in rows if (item := normalize_record(row, default_supplier=supplier, default_source_type=source_type, mode="fixture")))


def import_csv(path: str | Path, *, supplier: str = "manual", source_type: str = "manual_csv_import") -> list[SupplierFeasibilityEvidence]:
    rows = list(csv.DictReader(io.StringIO(_read_import_text(path, encoding="utf-8-sig"))))
    return collapse_duplicates(item for row in rows if (item := normalize_record(row, default_supplier=str(row.get("supplier") or supplier), default_source_type=str(row.get("source_type") or source_type), mode="manual_import")))


def import_cj_validation_pack(path: str | Path) -> list[SupplierFeasibilityEvidence]:
    return import_json(path, supplier="cj", source_type="cj_validation_pack_report")


def import_cj_manual(path: str | Path) -> list[SupplierFeasibilityEvidence]:
    return import_csv(path, supplier="cj", source_type="cj_manual_import")


def import_alibaba(path: str | Path, *, source_type: str = "alibaba_supplier_snapshot") -> list[SupplierFeasibilityEvidence]:
    return import_json(path, supplier="alibaba", source_type=source_type)


def import_aliexpress(path: str | Path) -> list[SupplierFeasibilityEvidence]:
    return import_json(path, supplier="aliexpress", source_type="aliexpress_supplier_snapshot")


def import_supplier_csv(path: str | Path, supplier: str, source_type: str) -> list[SupplierFeasibilityEvidence]:
    return import_csv(path, supplier=supplier, source_type=source_type)
