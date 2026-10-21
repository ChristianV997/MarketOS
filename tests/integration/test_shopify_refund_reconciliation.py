import json

from backend.ecommerce.shopify_readonly.orders_csv import parse_shopify_orders_refunds_csv
from backend.ecommerce.shopify_readonly.reporting import report_to_dict, report_to_markdown


def _report(text: str) -> dict:
    result = parse_shopify_orders_refunds_csv(text)
    assert result.status == "accepted"
    assert result.batch is not None and result.context is not None
    return report_to_dict(result.batch, result.context)


def test_reconciles_successful_transactions_by_currency_without_sku_allocation():
    report = _report(
        "\n".join(
            [
                "Record type,Id,Name,Currency,Total,Refunded Amount,Lineitem name,Lineitem sku,Refund Id,Order Id,Amount,Transaction status,Created at",
                "order,1001,#1001,USD,100.00,10.00,Widget,SKU-1,,,,,2024-01-01",
                "refund,,,USD,,,,,r1,1001,10.00,SUCCESS,2024-01-02",
                "order,1002,#1002,MXN,80.00,0.00,Thing,SKU-2,,,,,2024-01-01",
                "refund,,,MXN,,,,,r2,1002,0.00,success,2024-01-02",
            ]
        )
    )

    reconciliation = report["refund_reconciliation"]
    assert reconciliation["status"] == "reconciled"
    assert reconciliation["order_level_refund_totals"] == {"MXN": "0.00", "USD": "10.00"}
    assert reconciliation["successful_transaction_totals"] == {"MXN": "0.00", "USD": "10.00"}
    assert reconciliation["variance_by_currency"] == {"MXN": "0.00", "USD": "0.00"}
    assert reconciliation["transaction_status_counts"] == {
        "successful": 2,
        "pending": 0,
        "failed": 0,
        "missing": 0,
        "unknown": 0,
    }
    assert reconciliation["line_item_refund_attribution"]["status"] == "unavailable"
    assert reconciliation["line_item_refund_attribution"]["allocation"] == "not_performed"
    assert reconciliation["line_item_refund_attribution"]["attributed_line_item_count"] == 0
    assert "SKU-1" not in report["refund_reconciliation"]["line_item_refund_attribution"].get("source_fields", [])
    assert "SKU-2" not in report["refund_reconciliation"]["line_item_refund_attribution"].get("source_fields", [])


def test_non_successful_or_unbound_transactions_are_not_reconciled():
    report = _report(
        "\n".join(
            [
                "Record type,Id,Name,Currency,Total,Refunded Amount,Refund Id,Order Id,Amount,Transaction status,Created at",
                "order,1001,#1001,USD,100.00,15.00,,,,,2024-01-01",
                "refund,,,USD,,,r-pending,1001,10.00,PENDING,2024-01-02",
                "refund,,,USD,,,r-failed,1001,5.00,FAILED,2024-01-03",
                "refund,,,USD,,,r-missing-status,1001,0.00,,2024-01-04",
                "refund,,,USD,,,r-missing-amount,1001,,SUCCESS,2024-01-05",
                "refund,,,USD,,,r-unmatched,9999,2.00,SUCCESS,2024-01-06",
                "refund,,,EUR,,,r-currency,1001,15.00,success,2024-01-07",
            ]
        )
    )

    reconciliation = report["refund_reconciliation"]
    assert reconciliation["status"] == "inconsistent"
    assert reconciliation["transaction_status_counts"] == {
        "successful": 3,
        "pending": 1,
        "failed": 1,
        "missing": 1,
        "unknown": 0,
    }
    assert reconciliation["missing_amount_transaction_count"] == 1
    assert len(reconciliation["unmatched_transaction_ids"]) == 1
    assert len(reconciliation["currency_mismatch_transaction_ids"]) == 1
    serialized = json.dumps(report, sort_keys=True)
    assert "r-unmatched" not in serialized
    assert "r-currency" not in serialized
    assert reconciliation["successful_transaction_totals"] == {"EUR": "15.00", "USD": "2.00"}
    assert reconciliation["reconciled_order_ids"] == []
    assert reconciliation["inconsistent_order_ids"] == []


def test_report_is_deterministic_and_markdown_keeps_manual_boundary():
    text = "Id,Name,Currency,Total,Refunded Amount\n1001,#1001,USD,10.00,0.00\n"
    first = _report(text)
    second = _report(text)
    assert first == second
    assert first["refund_reconciliation"]["status"] == "unavailable"
    assert first["refund_reconciliation"]["order_level_refund_totals"] == {"USD": "0.00"}
    assert first["refund_reconciliation"]["successful_transaction_totals"] == {}
    assert first["refund_reconciliation"]["refund_scope_counts"] == {
        "none": 1,
        "partial": 0,
        "full": 0,
        "over_refunded": 0,
        "unknown": 0,
    }
    markdown = report_to_markdown(
        parse_shopify_orders_refunds_csv(text).batch,
        parse_shopify_orders_refunds_csv(text).context,
    )
    assert "Refund reconciliation" in markdown
    assert "Manual/fixture input only" in markdown
    assert "live validation" in markdown


def test_display_name_fallback_is_not_an_exact_reconciliation_key():
    report = _report(
        "\n".join(
            [
                "Record type,Id,Name,Currency,Total,Refunded Amount,Refund Id,Order Id,Amount,Transaction status,Created at",
                "order,,#1001,USD,100.00,10.00,,,,,2024-01-01",
                "refund,,#1001,USD,,,r1,,10.00,SUCCESS,2024-01-02",
            ]
        )
    )

    reconciliation = report["refund_reconciliation"]
    assert reconciliation["status"] == "partial"
    assert len(reconciliation["unverified_order_key_transaction_ids"]) == 1
    assert "r1" not in json.dumps(report, sort_keys=True)
    assert reconciliation["reconciled_order_ids"] == []


def test_negative_refund_amount_is_rejected_without_refund_evidence():
    result = parse_shopify_orders_refunds_csv(
        "Refund Id,Order Id,Amount,Currency\nr-negative,1001,-1.00,USD\n"
    )
    assert result.status == "rejected"
    assert result.batch is None
    assert result.rejections == (({"code": "malformed_amount", "row_number": 2, "field": "amount"}),)
    assert "-1.00" not in json.dumps(result.to_dict(), sort_keys=True)


def test_order_level_scope_preserves_partial_and_full_refunds():
    report = _report(
        "\n".join(
            [
                "Id,Name,Currency,Total,Refunded Amount",
                "1001,#1001,USD,100.00,25.00",
                "1002,#1002,USD,50.00,50.00",
            ]
        )
    )
    reconciliation = report["refund_reconciliation"]
    assert reconciliation["status"] == "unavailable"
    assert reconciliation["refund_scope_counts"] == {
        "none": 0,
        "partial": 1,
        "full": 1,
        "over_refunded": 0,
        "unknown": 0,
    }
    assert sorted(reconciliation["refund_scope_by_order"].values()) == ["full", "partial"]


def test_sku_gross_sales_are_separate_from_unavailable_refund_attribution():
    report = _report(
        "\n".join(
            [
                "Id,Name,Currency,Total,Refunded Amount,Lineitem sku,Lineitem quantity,Lineitem price",
                "1001,#1001,USD,20.00,5.00,SKU-1,2,10.00",
                "1002,#1002,USD,0.00,0.00,SKU-2,,",
            ]
        )
    )
    reconciliation = report["refund_reconciliation"]
    assert reconciliation["sku_gross_sales_by_currency"] == {"USD": {"SKU-1": "20.00"}}
    assert reconciliation["sku_gross_sales_unavailable_line_count"] == 1
    assert reconciliation["line_item_refund_attribution"]["status"] == "unavailable"
