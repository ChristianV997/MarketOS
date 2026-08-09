import pytest

from backend.contracts.adapters import SidecarContext
from backend.integrations.woocommerce.adapter import WooCommerceCommerceAdapter
from backend.integrations.woocommerce.client import WooCommerceClient


def test_health_unconfigured_without_env_vars(monkeypatch):
    monkeypatch.delenv("WOOCOMMERCE_STORE_URL", raising=False)
    monkeypatch.delenv("WOOCOMMERCE_CONSUMER_KEY", raising=False)
    monkeypatch.delenv("WOOCOMMERCE_CONSUMER_SECRET", raising=False)
    health = WooCommerceCommerceAdapter().health()
    assert health.configured is False
    assert health.reachable is False


def test_create_order_dry_run_makes_no_http_call():
    class Client:
        def request(self, *args, **kwargs):
            raise AssertionError("dry-run must not make HTTP calls")

    adapter = WooCommerceCommerceAdapter(client=WooCommerceClient(client=Client()))
    result = adapter.create_order({"line_items": []}, context=SidecarContext(dry_run=True, idempotency_key="a"))
    assert result["dry_run"] is True
    assert result["id"] == "dry-woo-order-a"


def test_create_cart_never_calls_woocommerce_even_when_live():
    class Client:
        def request(self, *args, **kwargs):
            raise AssertionError("create_cart must never call WooCommerce (no server-side cart resource)")

    adapter = WooCommerceCommerceAdapter(client=WooCommerceClient(client=Client()))
    result = adapter.create_cart({"line_items": []}, context=SidecarContext(dry_run=False, approval_state="approved", idempotency_key="a"))
    assert result["staged_locally"] is True


def test_complete_cart_requires_approval_when_live():
    adapter = WooCommerceCommerceAdapter(client=WooCommerceClient(consumer_key="k", consumer_secret="s", store_url="https://example.com"))
    adapter.create_cart({"line_items": []}, context=SidecarContext(idempotency_key="cart-1"))
    with pytest.raises(PermissionError):
        adapter.complete_cart("woo-cart-cart-1", context=SidecarContext(dry_run=False, idempotency_key="cart-1"))


def test_refund_rejects_non_positive_amount():
    adapter = WooCommerceCommerceAdapter()
    with pytest.raises(ValueError):
        adapter.refund_order_payment("1", "pc-1", 0.0, context=SidecarContext(dry_run=True))


def test_fulfill_order_dry_run_stub():
    adapter = WooCommerceCommerceAdapter()
    result = adapter.fulfill_order("42", {"status": "completed"}, context=SidecarContext(dry_run=True, idempotency_key="f1"))
    assert result["dry_run"] is True
    assert result["order_id"] == "42"
