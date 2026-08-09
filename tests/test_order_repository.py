"""Tests for backend.data.repositories.order_repository — customers, orders,
fulfillment lifecycle, webhook dedupe."""
import pytest

from backend.data.repositories.order_repository import (
    CommerceOrder,
    CustomerRecord,
    OrderRepository,
)


@pytest.fixture
def repo(tmp_path):
    return OrderRepository(db_path=str(tmp_path / "test.db"))


class TestWebhookDedupe:
    def test_first_event_seen_returns_true(self, repo):
        assert repo.mark_event_seen("evt_1", source="stripe") is True

    def test_duplicate_event_returns_false(self, repo):
        repo.mark_event_seen("evt_1", source="stripe")
        assert repo.mark_event_seen("evt_1", source="stripe") is False

    def test_empty_event_id_always_true(self, repo):
        assert repo.mark_event_seen("") is True
        assert repo.mark_event_seen("") is True


class TestCustomers:
    def test_upsert_and_get(self, repo):
        repo.upsert_customer(CustomerRecord(
            customer_id="c1", email="a@x.com", name="Ana",
            shipping={"city": "Austin"},
        ))
        c = repo.get_customer("c1")
        assert c.email == "a@x.com"
        assert c.shipping["city"] == "Austin"

    def test_upsert_preserves_existing_name_on_blank_update(self, repo):
        repo.upsert_customer(CustomerRecord(customer_id="c1", email="a@x.com", name="Ana"))
        repo.upsert_customer(CustomerRecord(customer_id="c1", email="a@x.com", name=""))
        assert repo.get_customer("c1").name == "Ana"

    def test_unknown_customer_returns_none(self, repo):
        assert repo.get_customer("nope") is None


class TestOrders:
    def test_record_and_get(self, repo):
        order = CommerceOrder(
            order_id="o1", source="stripe", brand_id="beauty",
            product_id="jade-roller", qty=1, amount=19.99, currency="usd",
            customer_id="c1", utm={"utm_source": "tiktok"},
        )
        assert repo.record_order(order) is True
        fetched = repo.get_order("o1")
        assert fetched.amount == 19.99
        assert fetched.utm["utm_source"] == "tiktok"
        assert fetched.fulfillment_status == "RECEIVED"

    def test_duplicate_order_id_rejected(self, repo):
        order = CommerceOrder(order_id="o1", source="stripe", brand_id="b",
                              product_id="p", qty=1, amount=1.0, currency="usd",
                              customer_id="c1")
        assert repo.record_order(order) is True
        assert repo.record_order(order) is False  # idempotent replay

    def test_orders_by_status(self, repo):
        for oid in ("o1", "o2"):
            repo.record_order(CommerceOrder(
                order_id=oid, source="stripe", brand_id="b", product_id="p",
                qty=1, amount=1.0, currency="usd", customer_id="c1",
            ))
        received = repo.orders_by_status("RECEIVED")
        assert {o.order_id for o in received} == {"o1", "o2"}
        assert repo.orders_by_status("PLACED") == []


class TestFulfillmentTransitions:
    def _order(self, repo, order_id="o1"):
        repo.record_order(CommerceOrder(
            order_id=order_id, source="stripe", brand_id="b", product_id="p",
            qty=1, amount=1.0, currency="usd", customer_id="c1",
        ))

    def test_valid_transition_received_to_placed(self, repo):
        self._order(repo)
        assert repo.update_fulfillment("o1", "PLACED", supplier_name="cj",
                                       supplier_order_id="cj_123") is True
        order = repo.get_order("o1")
        assert order.fulfillment_status == "PLACED"
        assert order.supplier_name == "cj"
        assert order.supplier_order_id == "cj_123"

    def test_illegal_transition_rejected(self, repo):
        self._order(repo)
        # RECEIVED cannot jump straight to DELIVERED
        assert repo.update_fulfillment("o1", "DELIVERED") is False
        assert repo.get_order("o1").fulfillment_status == "RECEIVED"

    def test_full_lifecycle(self, repo):
        self._order(repo)
        assert repo.update_fulfillment("o1", "PLACED") is True
        assert repo.update_fulfillment("o1", "SHIPPED") is True
        assert repo.update_fulfillment("o1", "DELIVERED") is True
        assert repo.get_order("o1").fulfillment_status == "DELIVERED"

    def test_failed_can_retry_to_placed(self, repo):
        self._order(repo)
        repo.update_fulfillment("o1", "PLACED")
        # Simulate a failure then a retry
        conn = repo._connect()
        conn.execute("UPDATE commerce_orders SET fulfillment_status='FAILED' WHERE order_id='o1'")
        conn.commit()
        conn.close()
        assert repo.update_fulfillment("o1", "PLACED") is True

    def test_unknown_order_returns_false(self, repo):
        assert repo.update_fulfillment("nope", "PLACED") is False

    def test_invalid_status_returns_false(self, repo):
        self._order(repo)
        assert repo.update_fulfillment("o1", "BOGUS") is False
