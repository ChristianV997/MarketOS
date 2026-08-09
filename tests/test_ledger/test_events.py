"""Tests for backend.ledger.events."""
import uuid

from backend.ledger.events import (
    record_ad_spend_observed,
    record_order_canceled,
    record_order_created,
    record_payment_captured,
)
from backend.orchestration.event_store import event_store


def _ws() -> str:
    return f"ws-ledger-events-{uuid.uuid4().hex[:8]}"


def test_record_order_created_appends_event_with_workspace_scoping():
    ws = _ws()
    record = record_order_created(ws, "order-1", product_name="Widget", channel="meta", revenue=40.0)

    assert record["event"] == "OrderCreated"
    assert record["data"]["workspace_id"] == ws
    assert record["data"]["order_id"] == "order-1"
    assert record["data"]["revenue"] == 40.0

    matches = [
        e for e in event_store.events_of_type("OrderCreated")
        if e["data"]["workspace_id"] == ws
    ]
    assert len(matches) == 1


def test_record_payment_captured_and_order_canceled_round_trip():
    ws = _ws()
    record_order_created(ws, "order-2", revenue=25.0)
    payment = record_payment_captured(ws, "order-2", amount=25.0)
    cancel = record_order_canceled(ws, "order-2", reason="customer_request")

    assert payment["data"]["amount"] == 25.0
    assert cancel["data"]["reason"] == "customer_request"


def test_record_ad_spend_observed_defaults_channel_optional():
    ws = _ws()
    record = record_ad_spend_observed(ws, channel="tiktok", amount=12.5)
    assert record["data"]["channel"] == "tiktok"
    assert record["data"]["amount"] == 12.5


def test_events_never_raise_when_event_store_append_fails(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("disk full")
    monkeypatch.setattr(event_store, "append", _boom)

    record = record_order_created("ws-x", "order-x", revenue=10.0)  # must not raise
    assert record == {}
