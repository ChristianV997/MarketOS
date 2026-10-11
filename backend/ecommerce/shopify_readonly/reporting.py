"""Stable JSON/Markdown reporting for Shopify read-only import packets."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any

from .events import event_type_counts, shopify_batch_events
from .models import ShopifyImportBatch, ShopifyRefundObservation, ShopifyStoreContext

_CENT = Decimal("0.01")
_TRANSACTION_STATUSES = ("successful", "pending", "failed", "missing", "unknown")
_REFUND_SCOPES = ("none", "partial", "full", "over_refunded", "unknown")


def _decimal_amount(value: float | None) -> Decimal | None:
    if value is None:
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not amount.is_finite():
        return None
    return amount.quantize(_CENT)


def _add_amount(target: dict[str, Decimal], currency: str, amount: Decimal | None) -> None:
    if not currency or amount is None:
        return
    target[currency] = target.get(currency, Decimal("0")) + amount


def _money_map(target: dict[str, Decimal]) -> dict[str, str]:
    return {currency: str(target[currency].quantize(_CENT)) for currency in sorted(target)}


def _opaque_ref(prefix: str, value: str) -> str:
    digest = hashlib.sha256(f"{prefix}:{value}".encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _opaque_refs(prefix: str, values: list[str]) -> list[str]:
    return [_opaque_ref(prefix, value) for value in values]


def _sku_gross_sales(batch: ShopifyImportBatch) -> tuple[dict[str, dict[str, Decimal]], int]:
    orders = {order.order_id: order for order in batch.orders}
    totals: dict[str, dict[str, Decimal]] = defaultdict(dict)
    unavailable = 0
    for line in batch.line_items:
        order = orders.get(line.order_id)
        price = _decimal_amount(line.price)
        if (
            order is None
            or not order.currency
            or not line.sku
            or line.quantity is None
            or price is None
        ):
            unavailable += 1
            continue
        amount = (price * line.quantity).quantize(_CENT)
        totals[order.currency][line.sku] = totals[order.currency].get(line.sku, Decimal("0")) + amount
    return totals, unavailable


def _sku_money_map(target: dict[str, dict[str, Decimal]]) -> dict[str, dict[str, str]]:
    return {
        currency: {
            sku: str(amount.quantize(_CENT))
            for sku, amount in sorted(values.items())
        }
        for currency, values in sorted(target.items())
    }


def _refund_source(refund: ShopifyRefundObservation) -> str:
    source = refund.metadata.get("refund_source")
    if source in {"order_level", "transaction"}:
        return source
    return "order_level" if refund.refund_id.startswith("order-refund:") else "transaction"


def _transaction_status(refund: ShopifyRefundObservation) -> str:
    status = refund.metadata.get("transaction_status")
    return status if status in _TRANSACTION_STATUSES else "missing"


def build_refund_reconciliation(batch: ShopifyImportBatch) -> dict[str, Any]:
    """Summarize imported refund evidence without turning it into accounting truth.

    Order-level ``Refunded Amount`` observations and transaction rows are kept
    separate. Only successful transactions with a stable order key, matching
    currency, and an explicit amount are eligible for comparison. No refund is
    allocated to a line item unless the importer provides a stable relation;
    the current CSV contract does not provide one.
    """
    orders = {order.order_id: order for order in batch.orders}
    order_totals: dict[str, Decimal] = {}
    order_totals_by_order: dict[str, tuple[str, Decimal | None]] = {}
    transaction_totals: dict[str, dict[str, Decimal]] = {
        status: {} for status in _TRANSACTION_STATUSES
    }
    transaction_status_counts = {status: 0 for status in _TRANSACTION_STATUSES}
    successful_by_order: dict[str, dict[str, Decimal]] = defaultdict(dict)
    transaction_order_ids: set[str] = set()
    matched_successful_transaction_count = 0
    unmatched_transaction_ids: list[str] = []
    currency_mismatch_transaction_ids: list[str] = []
    missing_currency_transaction_ids: list[str] = []
    unverified_order_key_transaction_ids: list[str] = []
    missing_amount_transaction_ids: list[str] = []
    order_level_record_count = 0
    order_level_amount_count = 0
    transaction_record_count = 0
    refund_scope_by_order: dict[str, str] = {}
    refund_scope_counts = {scope: 0 for scope in _REFUND_SCOPES}

    for refund in sorted(batch.refunds, key=lambda item: item.refund_id):
        amount = _decimal_amount(refund.amount)
        source = _refund_source(refund)
        if source == "order_level":
            order_level_record_count += 1
            if amount is not None:
                order_level_amount_count += 1
                _add_amount(order_totals, refund.currency, amount)
            order_totals_by_order[refund.order_id] = (refund.currency, amount)
            order = orders.get(refund.order_id)
            order_total = _decimal_amount(None if order is None else order.total_price)
            if (
                order is None
                or not refund.currency
                or refund.currency != order.currency
                or amount is None
                or order_total is None
                or amount < 0
                or order_total < 0
            ):
                scope = "unknown"
            elif amount == 0:
                scope = "none"
            elif amount == order_total:
                scope = "full"
            elif amount < order_total:
                scope = "partial"
            else:
                scope = "over_refunded"
            refund_scope_by_order[refund.order_id] = scope
            refund_scope_counts[scope] += 1
            continue

        transaction_record_count += 1
        status = _transaction_status(refund)
        transaction_status_counts[status] += 1
        _add_amount(transaction_totals[status], refund.currency, amount)
        if amount is None:
            missing_amount_transaction_ids.append(refund.refund_id)
        transaction_order_ids.add(refund.order_id)

        order = orders.get(refund.order_id)
        if order is None:
            unmatched_transaction_ids.append(refund.refund_id)
            continue
        if refund.metadata.get("order_key_source") != "order_id" or order.metadata.get("order_key_source") not in {"id", "order_id"}:
            unverified_order_key_transaction_ids.append(refund.refund_id)
            continue
        if not refund.currency or not order.currency:
            missing_currency_transaction_ids.append(refund.refund_id)
            continue
        if refund.currency != order.currency:
            currency_mismatch_transaction_ids.append(refund.refund_id)
            continue
        if status == "successful" and amount is not None:
            _add_amount(successful_by_order[refund.order_id], refund.currency, amount)
            matched_successful_transaction_count += 1

    matched_order_ids: list[str] = []
    inconsistent_order_ids: list[str] = []
    uncovered_order_ids: list[str] = []
    variance: dict[str, Decimal] = {}
    for order_id, (currency, order_amount) in sorted(order_totals_by_order.items()):
        successful_amount = successful_by_order.get(order_id, {}).get(currency)
        if order_amount is None or successful_amount is None:
            uncovered_order_ids.append(order_id)
            continue
        delta = order_amount - successful_amount
        _add_amount(variance, currency, delta)
        if delta == 0:
            matched_order_ids.append(order_id)
        else:
            inconsistent_order_ids.append(order_id)

    has_non_successful = any(
        transaction_status_counts[status] for status in ("pending", "failed", "missing", "unknown")
    )
    has_coverage_gap = bool(
        uncovered_order_ids
        or missing_amount_transaction_ids
        or missing_currency_transaction_ids
        or unverified_order_key_transaction_ids
        or unmatched_transaction_ids
        or currency_mismatch_transaction_ids
        or has_non_successful
    )
    if not order_level_record_count or not transaction_record_count:
        reconciliation_status = "unavailable"
    elif inconsistent_order_ids or unmatched_transaction_ids or currency_mismatch_transaction_ids:
        reconciliation_status = "inconsistent"
    elif has_coverage_gap:
        reconciliation_status = "partial"
    else:
        reconciliation_status = "reconciled"

    sku_gross_sales, sku_gross_sales_unavailable_count = _sku_gross_sales(batch)
    return {
        "status": reconciliation_status,
        "order_level_refund_totals": _money_map(order_totals),
        "successful_transaction_totals": _money_map(transaction_totals["successful"]),
        "matched_successful_transaction_totals": _money_map(
            {
                currency: sum(
                    amounts.get(currency, Decimal("0"))
                    for amounts in successful_by_order.values()
                )
                for currency in sorted({
                    currency
                    for amounts in successful_by_order.values()
                    for currency in amounts
                })
            }
        ),
        "transaction_totals_by_status": {
            status: _money_map(transaction_totals[status])
            for status in _TRANSACTION_STATUSES
        },
        "transaction_status_counts": transaction_status_counts,
        "variance_by_currency": _money_map(variance),
        "refund_scope_by_order": {
            _opaque_ref("order", order_id): scope
            for order_id, scope in sorted(refund_scope_by_order.items())
        },
        "refund_scope_counts": refund_scope_counts,
        "sku_gross_sales_by_currency": _sku_money_map(sku_gross_sales),
        "sku_gross_sales_unavailable_line_count": sku_gross_sales_unavailable_count,
        "coverage": {
            "order_level_records": order_level_record_count,
            "order_level_records_with_amount": order_level_amount_count,
            "transaction_records": transaction_record_count,
            "orders_with_transaction_rows": len(transaction_order_ids),
            "matched_successful_transactions": matched_successful_transaction_count,
        },
        # Keep correlation useful without exposing source/payment identifiers.
        "reconciled_order_ids": _opaque_refs("order", matched_order_ids),
        "inconsistent_order_ids": _opaque_refs("order", inconsistent_order_ids),
        "uncovered_order_ids": _opaque_refs("order", uncovered_order_ids),
        "unmatched_transaction_ids": _opaque_refs("refund", sorted(unmatched_transaction_ids)),
        "currency_mismatch_transaction_ids": _opaque_refs("refund", sorted(currency_mismatch_transaction_ids)),
        "missing_currency_transaction_ids": _opaque_refs("refund", sorted(missing_currency_transaction_ids)),
        "unverified_order_key_transaction_ids": _opaque_refs("refund", sorted(unverified_order_key_transaction_ids)),
        "missing_amount_transaction_ids": _opaque_refs("refund", sorted(missing_amount_transaction_ids)),
        "missing_amount_transaction_count": len(missing_amount_transaction_ids),
        "line_item_refund_attribution": {
            "status": "unavailable",
            "attributed_line_item_count": 0,
            "allocation": "not_performed",
            "reason": "the imported CSV has no stable refund-to-line-item relation",
        },
        "source_boundary": "manual_import_not_live_transaction_validation",
    }


def report_to_dict(batch: ShopifyImportBatch, context: ShopifyStoreContext) -> dict[str, Any]:
    events = shopify_batch_events(batch, context)
    return {
        "workspace_id": batch.workspace_id,
        "source": batch.source,
        "mode": batch.mode,
        "product_count": len(batch.products),
        "variant_count": len(batch.variants),
        "collection_count": len(batch.collections),
        "order_count": len(batch.orders),
        "line_item_count": len(batch.line_items),
        "customer_count": len(batch.customers),
        "refund_count": len(batch.refunds),
        "skipped_count": len(batch.skipped_records),
        "warnings": list(context.warnings),
        "observed_revenue_total": context.observed_revenue_total,
        "observed_refund_total": context.metadata.get("observed_refund_total"),
        "observed_refund_total_basis": "all_imported_refund_observations_not_successful_only",
        "refund_reconciliation": build_refund_reconciliation(batch),
        "average_order_value": context.average_order_value,
        "active_product_count": context.active_product_count,
        "out_of_stock_variant_count": context.out_of_stock_variant_count,
        "pii_redacted": context.pii_redacted,
        "canonical_event_count": len(events),
        "event_type_counts": event_type_counts(events),
        "forbidden_actions": [
            "create_product",
            "update_product",
            "publish_product",
            "mutate_inventory",
            "create_order",
            "capture_payment",
            "refund",
            "fulfill",
            "message_customer",
        ],
        "next_recommended_step": "Review the PII-redacted packet manually; future authenticated read-only access requires explicit least-privilege scope review.",
        "network_calls": False,
        "mutated": False,
        "evidence_state": "manual_import" if batch.refunds or batch.metadata.get("evidence_state") == "manual_import" else "manual_export",
    }


def report_to_markdown(batch: ShopifyImportBatch, context: ShopifyStoreContext) -> str:
    report = report_to_dict(batch, context)
    reconciliation = report["refund_reconciliation"]
    return "\n".join(
        [
            "# Shopify read-only import packet",
            "",
            f"- Workspace: `{report['workspace_id']}`",
            f"- Products / orders: {report['product_count']} / {report['order_count']}",
            f"- PII redacted: `{report['pii_redacted']}`",
            "",
            "## Safety",
            "",
            "- Manual/fixture input only. No Shopify API call, mutation, publishing, payment, fulfillment, refund, or customer message was executed; this is not live validation or transaction authority.",
            "",
            "## Refund reconciliation",
            "",
            f"- Status: `{reconciliation['status']}`",
            f"- Order-level totals by currency: `{json.dumps(reconciliation['order_level_refund_totals'], sort_keys=True)}`",
            f"- Successful transaction totals by currency: `{json.dumps(reconciliation['successful_transaction_totals'], sort_keys=True)}`",
            f"- Line-item refund attribution: `{reconciliation['line_item_refund_attribution']['status']}`",
            "- Missing or non-successful transaction evidence remains a coverage gap; it is not treated as a successful refund.",
            "",
            "## Context",
            "",
            f"- Observed revenue total: {report['observed_revenue_total']} (historical export context only; not a forecast)",
            f"- Observed AOV: {report['average_order_value']} (not a profitability or demand claim)",
            "",
        ]
    ) + "\n"


__all__ = ["build_refund_reconciliation", "report_to_dict", "report_to_markdown"]
