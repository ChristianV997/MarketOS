from pathlib import Path

from backend.ecommerce.shopify_readonly.events import shopify_batch_events
from backend.ecommerce.shopify_readonly.orders_csv import (
    MAX_BYTES,
    MAX_ROWS,
    import_shopify_orders_csv,
    parse_shopify_orders_refunds_csv,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/shopify_readonly/orders_refunds_sample.csv"
PII = "ada@example.test"


def _events(text: str):
    result = parse_shopify_orders_refunds_csv(text)
    assert result.batch is not None and result.context is not None
    return result, shopify_batch_events(result.batch, result.context)


def test_valid_orders_refunds_are_deterministic_manual_import_events():
    text = FIXTURE.read_text(encoding="utf-8")
    first, events = _events(text)
    second = parse_shopify_orders_refunds_csv(text)
    assert first.status == "accepted"
    assert first.batch is not None and second.batch is not None
    assert first.batch.to_dict() == second.batch.to_dict()
    again = shopify_batch_events(second.batch, second.context)
    assert [item.replay_hash() for item in events] == [item.replay_hash() for item in again]
    orders = [item for item in events if item.event_type == "shopify_order_observed"]
    refunds = [item for item in events if item.event_type == "shopify_refund_observed"]
    assert [item.aggregate_id for item in orders] == ["1001", "1002"]
    assert orders[0].payload["total_price"] == 40.0
    assert orders[1].payload["total_price"] is None
    assert orders[1].payload["subtotal_price"] == 0.0
    assert len(orders[0].payload["line_item_ids"]) == 2
    assert {item.payload["amount"] for item in refunds} == {5.0, 0.0}
    assert first.context is not None
    assert first.context.metadata["observed_refund_total"] == 5.0
    assert all(item.metadata["no_refund_authority"] is True for item in events)
    assert all(item.metadata["read_only"] is True for item in events)
    blob = "\n".join(item.canonical_json() for item in events) + str(first.to_dict())
    assert PII not in blob
    assert "555-0100" not in blob
    assert "Ada Example" not in blob
    assert "1 Main Street" not in blob


def test_duplicate_rows_collapse_and_conflicts_do_not_import():
    header = "Id,Name,Currency,Total,Created at\n"
    duplicate = header + "1001,#1001,USD,10.00,2024-01-02\n1001,#1001,USD,10.00,2024-01-02\n"
    result, events = _events(duplicate)
    assert len(result.batch.orders) == 1
    assert sum(item.event_type == "shopify_order_observed" for item in events) == 1
    conflict = header + "1001,#1001,USD,10.00,2024-01-02\n1001,#1001,USD,12.00,2024-01-02\n"
    rejected = parse_shopify_orders_refunds_csv(conflict)
    assert rejected.status == "rejected" and rejected.batch is None
    assert rejected.rejections[0]["code"] == "conflicting_identity"
    assert "12.00" not in str(rejected.to_dict())


def test_missing_refund_is_not_zero_and_malformed_rows_are_rejected():
    missing = "Id,Name,Currency,Total,Refunded Amount\n1001,#1001,USD,10.00,\n"
    result, events = _events(missing)
    assert result.batch.orders[0].total_price == 10.0
    assert not any(item.event_type == "shopify_refund_observed" for item in events)
    assert "observed_refund_total" not in result.context.metadata
    malformed = "Id,Name,Currency,Total,Created at\n1001,#1001,US,10.00,2024-01-02\n1002,#1002,USD,3.00,yesterday\nnot an id,#1003,USD,3.00,2024-01-02\n1004,#1004,USD,3.00,2024-02-31\n1005,#1005,USD,1000000000001.00,2024-01-02\n"
    rejected = parse_shopify_orders_refunds_csv(malformed)
    assert rejected.status == "rejected"
    assert {item["code"] for item in rejected.rejections} >= {"malformed_currency", "malformed_identity", "malformed_date", "malformed_amount"}
    assert "yesterday" not in str(rejected.to_dict())
    assert "not an id" not in str(rejected.to_dict())
    zoned, zoned_events = _events("Id,Name,Currency,Total,Created at\n1006,#1006,USD,4.00,2024-01-02T00:00:00Z\n")
    assert zoned.batch.orders[0].created_at == "2024-01-02T00:00:00Z"
    assert zoned_events[1].event_type == "shopify_order_observed"
    contact = "Id,Name,Financial Status,Total\n1007,#1007,ada@example.test,10.00\n"
    hidden = parse_shopify_orders_refunds_csv(contact)
    assert hidden.status == "rejected"
    assert any(item["code"] == "malformed_identity" for item in hidden.rejections)
    assert "ada@example.test" not in str(hidden.to_dict())


def test_refund_file_missing_amount_conflicts_and_pii_do_not_leak():
    text = "\n".join([
        "Refund Id,Order Id,Amount,Currency,Created at,Email",
        "r1,1001,15.00,USD,2024-02-01T00:00:00Z,ada@example.test",
        "r1,1001,15.00,USD,2024-02-01T00:00:00Z,ada@example.test",
        "r2,1001,,USD,2024-02-02,ada@example.test",
        "r3,1001,4.00,USD,2024-02-03,ada@example.test",
        "r3,1001,9.00,USD,2024-02-03,ada@example.test",
    ])
    result = parse_shopify_orders_refunds_csv(text)
    assert result.status == "accepted"
    amounts = {item.refund_id: item.amount for item in result.batch.refunds}
    assert amounts == {"r1": 15.0, "r2": None}
    assert "r3" not in amounts
    assert any(item["code"] == "conflicting_identity" for item in result.rejections)
    assert result.context.metadata["observed_refund_total"] == 15.0
    assert result.context.metadata["refund_amount_missing_count"] == 1
    blob = str(result.to_dict()) + result.batch.to_dict().__repr__()
    assert "ada@example.test" not in blob
    assert "pii_columns_dropped:email" in result.batch.warnings


def test_unsupported_column_limits_and_path_import():
    rejected = parse_shopify_orders_refunds_csv("Id,Name,Gift Message\n1001,#1001,secret note\n")
    assert rejected.status == "rejected"
    assert rejected.rejections == ({"code": "unsupported_column", "field": "gift message"},)
    assert "secret note" not in str(rejected.to_dict())
    huge = "Id,Name\n" + "".join(f"{index},#{index}\n" for index in range(MAX_ROWS + 1))
    assert parse_shopify_orders_refunds_csv(huge).rejections[0]["code"] == "row_limit_exceeded"
    path = FIXTURE.with_name("orders_refunds_too_large.csv")
    path.write_bytes(b"x" * (MAX_BYTES + 1))
    try:
        assert import_shopify_orders_csv(path).rejections[0]["code"] == "file_too_large"
    finally:
        path.unlink()
    loaded = import_shopify_orders_csv(FIXTURE)
    assert loaded.status == "accepted" and loaded.batch is not None and len(loaded.batch.orders) == 2


def test_contact_text_is_not_emitted_and_order_refunds_merge():
    phone = parse_shopify_orders_refunds_csv("Id,Name,Total\n1001,555-010-0000,10.00\n")
    assert phone.status == "rejected"
    assert "555-010-0000" not in str(phone.to_dict())
    titled = parse_shopify_orders_refunds_csv("Id,Name,Total,Lineitem name\n1001,#1001,10.00,Call (555) 010-0000 now\n")
    assert titled.status == "accepted" and titled.batch is not None
    assert titled.batch.line_items == ()
    assert "555" not in str(titled.batch.to_dict())
    header = parse_shopify_orders_refunds_csv("Id,ada@example.test\n1001,secret\n")
    assert header.rejections[0]["field"] == "redacted"
    assert "ada@example.test" not in str(header.to_dict())
    billing = parse_shopify_orders_refunds_csv("Id,Total,Billing ada@example.test\n1001,10.00,secret\n")
    assert billing.status == "accepted" and billing.batch is not None
    assert "ada@example.test" not in str(billing.to_dict()) + str(billing.batch.warnings)
    repeated = "\n".join([
        "Id,Name,Total,Refunded Amount,Created at",
        "1001,#1001,10.00,5.00,",
        "1001,#1001,10.00,5.00,2024-01-02",
    ])
    merged = parse_shopify_orders_refunds_csv(repeated)
    assert merged.batch is not None and merged.context is not None
    assert [(item.amount, item.created_at) for item in merged.batch.refunds] == [(5.0, "2024-01-02")]
    assert merged.context.metadata["observed_refund_total"] == 5.0
