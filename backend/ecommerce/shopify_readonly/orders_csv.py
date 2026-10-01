"""Manual Shopify orders/refunds CSV import.

Maps a bounded operator file onto the existing Shopify read-only observations
and canonical events. Customer names, email, phone, and addresses are dropped
before any record or rejection is emitted. This does not call Shopify and does
not create, refund, or mutate an order.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from .importer import build_store_context
from .models import (
    ShopifyImportBatch,
    ShopifyLineItemObservation,
    ShopifyOrderObservation,
    ShopifyRefundObservation,
    ShopifyStoreContext,
)

MAX_BYTES = 1_048_576
MAX_ROWS = 5_000
_SOURCE = "manual://shopify-orders-csv"
_IDENTITY = re.compile(r"^[A-Za-z0-9#_\-:.]+$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_DATE = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2}| UTC)?)?$"
)
_AMOUNT = re.compile(r"\d+(?:\.\d+)?")
_PHONE = re.compile(r"(?:\+\d{1,3}[\s.\-]?)?(?:\(\d{3}\)[\s.\-]*\d{3}[\s.\-]?\d{4}|\d{3}[\s.\-]\d{3}[\s.\-]\d{4})")
_STREET = re.compile(r"\d+\s+[A-Za-z0-9.'-]+\s+(?:street|st|avenue|ave|road|rd|drive|dr|lane|ln|blvd|boulevard)\b", re.IGNORECASE)

_MAPPED = {
    "id": "id",
    "name": "name",
    "order id": "order_id",
    "order name": "name",
    "created at": "created_at",
    "financial status": "financial_status",
    "fulfillment status": "fulfillment_status",
    "cancelled at": "cancelled_at",
    "canceled at": "cancelled_at",
    "currency": "currency",
    "subtotal": "subtotal",
    "subtotal price": "subtotal",
    "total": "total",
    "total price": "total",
    "taxes": "tax",
    "total tax": "tax",
    "discount amount": "discounts",
    "total discounts": "discounts",
    "refunded amount": "refunded_amount",
    "refund amount": "refunded_amount",
    "amount": "amount",
    "lineitem quantity": "line_quantity",
    "lineitem name": "line_name",
    "lineitem price": "line_price",
    "lineitem sku": "line_sku",
    "lineitem discount": "line_discount",
    "record type": "record_type",
    "refund id": "refund_id",
}
_PII = {
    "email", "phone", "notes", "note attributes", "customer", "customer name",
    "billing name", "billing street", "billing address1", "billing address2", "billing company",
    "billing city", "billing zip", "billing province", "billing country", "billing phone",
    "billing province name", "shipping name", "shipping street", "shipping address1",
    "shipping address2", "shipping company", "shipping city", "shipping zip", "shipping province",
    "shipping country", "shipping phone", "shipping province name",
}
_IGNORED = {
    "paid at", "fulfilled at", "accepts marketing", "shipping", "discount code", "shipping method",
    "lineitem compare at price", "lineitem requires shipping", "lineitem taxable",
    "lineitem fulfillment status", "payment method", "payment reference", "payment id",
    "payment terms name", "next payment due at", "payment references", "vendor",
    "outstanding balance", "tags", "risk level", "source", "duties", "receipt number",
}


def _has_contact(text: str) -> bool:
    return "@" in text or _PHONE.search(text) is not None or _STREET.search(text) is not None


def _public_header(header: str) -> str:
    if _has_contact(header) or not re.fullmatch(r"[a-z0-9 ]{1,48}", header):
        return "redacted"
    return header


def _header(value: str) -> str:
    return " ".join(value.strip().lower().replace("_", " ").split())


def _classify_header(header: str) -> str:
    if header in _PII or header.startswith("billing ") or header.startswith("shipping "):
        return "pii"
    if re.fullmatch(r"tax \d+ (name|value)", header):
        return "ignored"
    if header in _IGNORED:
        return "ignored"
    if header in _MAPPED:
        return "mapped"
    return "unsupported"


def _rejection(row_number: int | None, code: str, field: str = "") -> dict[str, Any]:
    item: dict[str, Any] = {"code": code}
    if row_number is not None:
        item["row_number"] = row_number
    if field:
        item["field"] = field
    return item


def _amount(raw: str) -> tuple[float | None, str | None]:
    text = raw.strip()
    if text == "":
        return None, None
    negative = text.startswith("(") and text.endswith(")")
    cleaned = text.strip("()").replace("$", "").replace(",", "").strip()
    if cleaned.startswith("-"):
        negative = True
        cleaned = cleaned[1:].strip()
    if not _AMOUNT.fullmatch(cleaned):
        return None, "malformed_amount"
    try:
        value = Decimal(cleaned).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None, "malformed_amount"
    if negative:
        value = -value
    if abs(value) > Decimal("1000000000000"):
        return None, "malformed_amount"
    return float(value), None


def _date(raw: str) -> tuple[str | None, str | None]:
    text = " ".join(raw.strip().split())
    if text == "":
        return None, None
    if not _DATE.fullmatch(text):
        return None, "malformed_date"
    candidate = text[:-4] + "+00:00" if text.endswith(" UTC") else text
    if "T" not in candidate and " " in candidate:
        candidate = candidate.replace(" ", "T", 1)
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    offset = re.search(r"([+-]\d{2})(\d{2})$", candidate)
    if offset:
        candidate = candidate[:-5] + offset.group(1) + ":" + offset.group(2)
    try:
        datetime.fromisoformat(candidate)
    except ValueError:
        return None, "malformed_date"
    return text, None


def _currency(raw: str) -> tuple[str, str | None]:
    text = raw.strip().upper()
    if text == "":
        return "", None
    if not _CURRENCY.fullmatch(text):
        return "", "malformed_currency"
    return text, None


def _identity(raw: str) -> tuple[str, str | None]:
    text = raw.strip()
    if text == "" or len(text) > 64 or not _IDENTITY.fullmatch(text) or _has_contact(text):
        return "", "malformed_identity"
    return text, None


def _stable_id(prefix: str, value: str) -> str:
    return f"{prefix}-{hashlib.sha256(value.encode()).hexdigest()[:16]}"


@dataclass(frozen=True)
class ShopifyCsvImportResult:
    status: str
    rejections: tuple[dict[str, Any], ...]
    batch: ShopifyImportBatch | None = None
    context: ShopifyStoreContext | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "rejections": [dict(item) for item in self.rejections],
            "evidence_state": "manual_import",
            "live_validated": False,
            "network_calls": False,
            "mutated": False,
            "pii_redacted": True,
            "batch_id": None if self.batch is None else self.batch.batch_id,
            "order_count": 0 if self.batch is None else len(self.batch.orders),
            "refund_count": 0 if self.batch is None else len(self.batch.refunds),
            "observed_refund_total": None if self.context is None else self.context.metadata.get("observed_refund_total"),
        }


def _reject(rejections: list[dict[str, Any]]) -> ShopifyCsvImportResult:
    return ShopifyCsvImportResult("rejected", tuple(rejections))


def parse_shopify_orders_refunds_csv(text: str, workspace_id: str = "commerce-mvp-dry-run") -> ShopifyCsvImportResult:
    """Parse CSV text already decoded by the caller. Does not read the network."""
    if len(text.encode("utf-8")) > MAX_BYTES:
        return _reject([_rejection(None, "file_too_large")])
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return _reject([_rejection(None, "empty_csv")])
    headers = [_header(name) for name in reader.fieldnames if name and name.strip()]
    if any(not name or not name.strip() for name in reader.fieldnames):
        return _reject([_rejection(None, "empty_header")])
    if len(headers) != len(set(headers)):
        return _reject([_rejection(None, "duplicate_header")])
    unsupported = [header for header in headers if _classify_header(header) == "unsupported"]
    if unsupported:
        return _reject([_rejection(None, "unsupported_column", _public_header(header)) for header in sorted(set(_public_header(item) for item in unsupported))])
    mapped_headers = {header for header in headers if _classify_header(header) == "mapped"}
    pii_headers = sorted(header for header in headers if _classify_header(header) == "pii")
    if "record type" in mapped_headers:
        file_kind = "mixed"
    elif "refund id" in mapped_headers and "lineitem name" not in mapped_headers and "total" not in mapped_headers and "subtotal" not in mapped_headers:
        file_kind = "refund"
    else:
        file_kind = "order"
    if file_kind == "order" and "amount" in mapped_headers and "refunded amount" not in mapped_headers and "refund amount" not in mapped_headers:
        return _reject([_rejection(None, "unsupported_column", "amount")])

    rejections: list[dict[str, Any]] = []
    orders: dict[str, dict[str, Any]] = {}
    refunds: dict[str, dict[str, Any]] = {}
    conflicts: set[str] = set()
    row_count = 0
    for row_number, raw in enumerate(reader, start=2):
        row_count += 1
        if row_count > MAX_ROWS:
            return _reject([_rejection(None, "row_limit_exceeded")])
        if raw is None:
            continue
        if any(key is None for key in raw):
            return _reject([_rejection(row_number, "unsupported_column", "extra")])
        cells = {_header(key): (value or "") for key, value in raw.items() if key}
        kind = file_kind
        if file_kind == "mixed":
            label = cells.get("record type", "").strip().lower()
            if label not in {"order", "refund"}:
                rejections.append(_rejection(row_number, "malformed_record_type", "record type"))
                continue
            kind = label
        if kind == "refund":
            _take_refund(row_number, cells, refunds, rejections, conflicts)
        else:
            _take_order(row_number, cells, orders, refunds, rejections, conflicts)

    for order_id in sorted(key.removeprefix("order:") for key in conflicts if key.startswith("order:")):
        orders.pop(order_id, None)
    refunds = {
        key: value for key, value in refunds.items()
        if f"order:{value['order_id']}" not in conflicts and f"refund:{key}" not in conflicts
    }
    if not orders and not refunds:
        if not rejections:
            rejections.append(_rejection(None, "no_data_rows"))
        return _reject(rejections)

    order_models, line_models = _order_models(orders)
    refund_models = _refund_models(refunds)
    fingerprint = json.dumps(
        {"orders": [item.to_dict() for item in order_models], "lines": [item.to_dict() for item in line_models], "refunds": [item.to_dict() for item in refund_models]},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    digest = hashlib.sha256(f"{workspace_id}:{fingerprint}".encode()).hexdigest()
    warnings = ["read_only_advisory_import: no provider API was called and no mutation is possible", "manual_import_evidence: not live validation or transaction authority"]
    if pii_headers:
        safe_headers = sorted({_public_header(header) for header in pii_headers if _public_header(header) != "redacted"})
        hidden_headers = sum(_public_header(header) == "redacted" for header in pii_headers)
        if safe_headers:
            warnings.append("pii_columns_dropped:" + ",".join(safe_headers))
        if hidden_headers:
            warnings.append(f"pii_columns_redacted:{hidden_headers}")
    if rejections:
        warnings.append(f"skipped_records:{len(rejections)}")
    batch = ShopifyImportBatch(
        f"shopify-import-{digest[:20]}", workspace_id, _SOURCE, "manual_import",
        float(1_700_000_000 + int(digest[:8], 16) % 1_000_000), (), (), (),
        order_models, line_models, (), tuple(warnings), tuple(item["code"] for item in rejections),
        {"pii_redacted": True, "network_used": False, "provider_calls": False, "evidence_state": "manual_import", "live_validated": False, "no_refund_authority": True},
        refund_models,
    )
    return ShopifyCsvImportResult("accepted", tuple(rejections), batch, build_store_context(batch))


def import_shopify_orders_csv(path: str | Path, workspace_id: str = "commerce-mvp-dry-run") -> ShopifyCsvImportResult:
    """Read a local CSV. Over-limit files are rejected before parsing."""
    source = Path(path)
    if source.stat().st_size > MAX_BYTES:
        return _reject([_rejection(None, "file_too_large")])
    data = source.read_bytes()
    if len(data) > MAX_BYTES:
        return _reject([_rejection(None, "file_too_large")])
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return _reject([_rejection(None, "undecodable")])
    return parse_shopify_orders_refunds_csv(text, workspace_id)


def _mapped(cells: dict[str, str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for header, raw in cells.items():
        key = _MAPPED.get(header)
        if key:
            values[key] = raw
    return values


def _label(raw: str, limit: int) -> tuple[str, str | None]:
    text = " ".join(raw.split()).strip()
    if _has_contact(text):
        return "", "malformed_identity"
    return text[:limit], None


def _check(row_number: int, field: str, error: str | None, rejections: list[dict[str, Any]]) -> bool:
    if error is None:
        return True
    rejections.append(_rejection(row_number, error, field))
    return False


def _same(current: Any, new: Any) -> bool:
    return current in (None, "") or new in (None, "") or current == new


def _take_order(row_number: int, cells: dict[str, str], orders: dict[str, dict[str, Any]], refunds: dict[str, dict[str, Any]], rejections: list[dict[str, Any]], conflicts: set[str]) -> None:
    values = _mapped(cells)
    order_id, id_error = _identity(values.get("id") or values.get("order_id") or values.get("name") or "")
    name, name_error = _identity(values.get("name") or order_id)
    if not _check(row_number, "id", id_error, rejections) or not order_id:
        return
    if values.get("name") and not _check(row_number, "name", name_error, rejections):
        return
    created_at, date_error = _date(values.get("created_at", ""))
    cancelled_at, cancelled_error = _date(values.get("cancelled_at", ""))
    currency, currency_error = _currency(values.get("currency", ""))
    subtotal, subtotal_error = _amount(values.get("subtotal", ""))
    total, total_error = _amount(values.get("total", ""))
    tax, tax_error = _amount(values.get("tax", ""))
    discounts, discount_error = _amount(values.get("discounts", ""))
    refunded, refund_error = _amount(values.get("refunded_amount", ""))
    financial, financial_error = _label(values.get("financial_status", ""), 40)
    fulfillment, fulfillment_error = _label(values.get("fulfillment_status", ""), 40)
    ok = all(_check(row_number, field, error, rejections) for field, error in (
        ("created at", date_error), ("cancelled at", cancelled_error), ("currency", currency_error),
        ("subtotal", subtotal_error), ("total", total_error), ("taxes", tax_error),
        ("discount amount", discount_error), ("refunded amount", refund_error),
        ("financial status", financial_error), ("fulfillment status", fulfillment_error),
    ))
    if not ok:
        conflicts.add(f"order:{order_id}")
        return
    incoming = {"order_name": name or order_id, "created_at": created_at, "currency": currency, "subtotal": subtotal, "total": total, "tax": tax, "discounts": discounts, "financial_status": financial, "fulfillment_status": fulfillment, "cancelled_at": cancelled_at}
    current = orders.get(order_id)
    if current is None:
        orders[order_id] = {**incoming, "lines": {}}
    else:
        for key, value in incoming.items():
            if not _same(current[key], value):
                rejections.append(_rejection(row_number, "conflicting_identity", key))
                conflicts.add(f"order:{order_id}")
                return
            if current[key] in (None, "") and value not in (None, ""):
                current[key] = value
    _take_line(row_number, order_id, values, orders[order_id]["lines"], rejections)
    if "refunded_amount" in values and values.get("refunded_amount", "").strip() != "":
        _attach_order_refund(row_number, order_id, currency, created_at, refunded, refunds, rejections, conflicts)


def _take_line(row_number: int, order_id: str, values: dict[str, str], lines: dict[str, dict[str, Any]], rejections: list[dict[str, Any]]) -> None:
    if not any(values.get(key, "").strip() for key in ("line_name", "line_sku", "line_quantity", "line_price")):
        return
    quantity_raw = values.get("line_quantity", "")
    quantity: int | None
    if quantity_raw.strip() == "":
        quantity = None
    elif re.fullmatch(r"\d{1,9}", quantity_raw.strip()):
        quantity = int(quantity_raw.strip())
    else:
        rejections.append(_rejection(row_number, "malformed_amount", "lineitem quantity"))
        return
    price, price_error = _amount(values.get("line_price", ""))
    discount, discount_error = _amount(values.get("line_discount", ""))
    if price_error or discount_error:
        rejections.append(_rejection(row_number, price_error or discount_error or "malformed_amount", "lineitem price"))
        return
    title, title_error = _label(values.get("line_name", ""), 120)
    sku, sku_error = _label(values.get("line_sku", ""), 64)
    if title_error or sku_error:
        rejections.append(_rejection(row_number, title_error or sku_error or "malformed_identity", "lineitem name"))
        return
    key = json.dumps({"title": title, "sku": sku, "quantity": quantity, "price": price, "discount": discount}, sort_keys=True)
    lines.setdefault(key, {"title": title, "sku": sku, "quantity": quantity, "price": price, "discount": discount})


def _attach_order_refund(row_number: int, order_id: str, currency: str, created_at: str | None, amount: float | None, refunds: dict[str, dict[str, Any]], rejections: list[dict[str, Any]], conflicts: set[str]) -> None:
    identity = f"order-refund:{order_id}"
    incoming = {"order_id": order_id, "created_at": created_at, "currency": currency, "amount": amount}
    current = refunds.get(identity)
    if current is None:
        refunds[identity] = incoming
        return
    for key, value in incoming.items():
        if not _same(current[key], value):
            rejections.append(_rejection(row_number, "conflicting_identity", "refunded amount"))
            conflicts.add(f"refund:{identity}")
            return
        if current[key] in (None, "") and value not in (None, ""):
            current[key] = value


def _take_refund(row_number: int, cells: dict[str, str], refunds: dict[str, dict[str, Any]], rejections: list[dict[str, Any]], conflicts: set[str]) -> None:
    values = _mapped(cells)
    refund_id, refund_error = _identity(values.get("refund_id") or values.get("id") or "")
    order_id, order_error = _identity(values.get("order_id") or values.get("name") or "")
    if not _check(row_number, "refund id", refund_error, rejections) or not refund_id:
        return
    if not _check(row_number, "order id", order_error, rejections) or not order_id:
        return
    created_at, date_error = _date(values.get("created_at", ""))
    currency, currency_error = _currency(values.get("currency", ""))
    amount, amount_error = _amount(values.get("refunded_amount", values.get("amount", "")))
    if not all(_check(row_number, field, error, rejections) for field, error in (("created at", date_error), ("currency", currency_error), ("amount", amount_error))):
        conflicts.add(f"refund:{refund_id}")
        return
    incoming = {"order_id": order_id, "created_at": created_at, "currency": currency, "amount": amount}
    current = refunds.get(refund_id)
    if current is None:
        refunds[refund_id] = incoming
        return
    if current != incoming:
        rejections.append(_rejection(row_number, "conflicting_identity", "refund id"))
        conflicts.add(f"refund:{refund_id}")


def _order_models(orders: dict[str, dict[str, Any]]) -> tuple[tuple[ShopifyOrderObservation, ...], tuple[ShopifyLineItemObservation, ...]]:
    order_models = []
    line_models = []
    for order_id in sorted(orders):
        item = orders[order_id]
        line_ids = []
        for index, key in enumerate(sorted(item["lines"])):
            line = item["lines"][key]
            line_id = _stable_id("line", f"{order_id}:{index}:{key}")
            line_ids.append(line_id)
            line_models.append(ShopifyLineItemObservation(line_id, order_id, None, None, line["title"], line["sku"], line["quantity"], line["price"], line["discount"], "", {"read_only": True, "evidence_state": "manual_import"}))
        order_models.append(ShopifyOrderObservation(order_id, item["order_name"], item["created_at"], item["currency"], item["subtotal"], item["total"], item["tax"], item["discounts"], item["financial_status"], item["fulfillment_status"], tuple(line_ids), None, "shopify_orders_csv", item["cancelled_at"], {"read_only": True, "evidence_state": "manual_import", "source": _SOURCE}))
    return tuple(order_models), tuple(line_models)


def _refund_models(refunds: dict[str, dict[str, Any]]) -> tuple[ShopifyRefundObservation, ...]:
    return tuple(
        ShopifyRefundObservation(refund_id, item["order_id"], item["created_at"], item["currency"], item["amount"], {"read_only": True, "evidence_state": "manual_import", "source": _SOURCE, "no_refund_authority": True})
        for refund_id, item in sorted(refunds.items())
    )


__all__ = ["MAX_BYTES", "MAX_ROWS", "ShopifyCsvImportResult", "import_shopify_orders_csv", "parse_shopify_orders_refunds_csv"]
