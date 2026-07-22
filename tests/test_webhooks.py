"""Tests for api.routes.webhooks — signed Stripe/Shopify order intake.

Fulfillment must trigger ONLY from a verified signature, never from an
unsigned or malformed payload, and never twice for the same event
(webhook retries are idempotent).
"""
import base64
import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch, tmp_path):
    import backend.core.persistence as pers
    monkeypatch.setattr(pers, "STATE_DIR", str(tmp_path))
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test_secret")
    monkeypatch.setenv("SHOPIFY_WEBHOOK_SECRET", "shpss_test_secret")
    yield


@pytest.fixture
def commerce(monkeypatch, tmp_path):
    from backend.commerce.brands import Brand, BrandRegistry
    from backend.commerce.catalog import STATUS_LIVE, CatalogEntry, ProductCatalog
    import backend.commerce.brands as brands_mod
    import backend.commerce.catalog as cat_mod
    from backend.data.repositories.order_repository import OrderRepository
    import backend.commerce.orders as orders_mod
    import api.routes.webhooks as webhooks_mod

    registry = BrandRegistry()
    catalog = ProductCatalog()
    monkeypatch.setattr(brands_mod, "brand_registry", registry)
    monkeypatch.setattr(cat_mod, "product_catalog", catalog)

    repo = OrderRepository(db_path=str(tmp_path / "orders.db"))
    monkeypatch.setattr(orders_mod, "order_repository", repo, raising=False)
    monkeypatch.setattr(webhooks_mod, "order_repository", repo, raising=False)
    import backend.data.repositories.order_repository as repo_mod
    monkeypatch.setattr(repo_mod, "order_repository", repo)

    from backend.data.repositories.roas_repository import RoasRepository
    monkeypatch.setattr(orders_mod, "_roas_repo",
                        RoasRepository(db_path=str(tmp_path / "roas.db")))

    registry.upsert(Brand(brand_id="beauty", name="Beauty Co", category="beauty"))
    catalog.register(CatalogEntry(
        product_id="jade-roller", brand_id="beauty", title="Jade Roller",
        retail_price=19.99, status=STATUS_LIVE,
    ))
    return repo


@pytest.fixture
def client():
    from backend.api import app
    return TestClient(app)


def _stripe_signature(body: bytes, secret: str, ts: int | None = None) -> str:
    ts = ts or int(time.time())
    signed_payload = f"{ts}.".encode() + body
    sig = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def _shopify_signature(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def _stripe_event(event_id="evt_1", session_id="cs_test_1", brand_id="beauty",
                   product_id="jade-roller", amount_cents=1999, event_type="checkout.session.completed"):
    return {
        "id": event_id,
        "type": event_type,
        "data": {"object": {
            "id": session_id,
            "amount_total": amount_cents,
            "currency": "usd",
            "metadata": {"brand_id": brand_id, "product_id": product_id,
                        "qty": "1", "utm_source": "tiktok"},
            "customer_details": {"email": "buyer@example.com", "name": "Buyer One"},
            "shipping_details": {"address": {
                "line1": "123 Main St", "city": "Austin", "state": "TX",
                "postal_code": "78701", "country": "US",
            }},
        }},
    }


class TestStripeWebhook:
    def test_missing_secret_returns_503(self, commerce, client, monkeypatch):
        monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
        resp = client.post("/webhooks/stripe", content=b"{}",
                           headers={"Stripe-Signature": "t=1,v1=x"})
        assert resp.status_code == 503

    def test_missing_signature_rejected(self, commerce, client):
        body = json.dumps(_stripe_event()).encode()
        resp = client.post("/webhooks/stripe", content=body)
        assert resp.status_code == 400

    def test_invalid_signature_rejected(self, commerce, client):
        body = json.dumps(_stripe_event()).encode()
        resp = client.post("/webhooks/stripe", content=body,
                           headers={"Stripe-Signature": "t=1,v1=deadbeef"})
        assert resp.status_code == 400

    def test_stale_timestamp_rejected(self, commerce, client):
        body = json.dumps(_stripe_event()).encode()
        old_sig = _stripe_signature(body, "whsec_test_secret", ts=int(time.time()) - 10_000)
        resp = client.post("/webhooks/stripe", content=body,
                           headers={"Stripe-Signature": old_sig})
        assert resp.status_code == 400

    def test_valid_signature_ingests_order(self, commerce, client):
        event = _stripe_event()
        body = json.dumps(event).encode()
        sig = _stripe_signature(body, "whsec_test_secret")
        resp = client.post("/webhooks/stripe", content=body,
                           headers={"Stripe-Signature": sig})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["is_new"] is True

        order = commerce.get_order("cs_test_1")
        assert order is not None
        assert order.amount == 19.99
        assert order.brand_id == "beauty"
        assert order.fulfillment_status == "RECEIVED"

        customer = commerce.get_customer(order.customer_id)
        assert customer.email == "buyer@example.com"
        assert customer.shipping["city"] == "Austin"

    def test_replayed_event_is_deduped(self, commerce, client):
        event = _stripe_event()
        body = json.dumps(event).encode()
        sig = _stripe_signature(body, "whsec_test_secret")
        client.post("/webhooks/stripe", content=body, headers={"Stripe-Signature": sig})
        resp2 = client.post("/webhooks/stripe", content=body, headers={"Stripe-Signature": sig})
        assert resp2.json().get("duplicate") is True

    def test_non_checkout_event_ignored(self, commerce, client):
        event = _stripe_event(event_id="evt_2", event_type="payment_intent.created")
        body = json.dumps(event).encode()
        sig = _stripe_signature(body, "whsec_test_secret")
        resp = client.post("/webhooks/stripe", content=body, headers={"Stripe-Signature": sig})
        assert resp.status_code == 200
        assert resp.json().get("ignored") == "payment_intent.created"
        assert commerce.get_order("cs_test_1") is None

    def test_unpaid_session_not_ingested_pending_async_payment(self, commerce, client):
        """A delayed payment method (ACH, SEPA) completes the *session*
        before the *payment* — ingesting here would place a supplier order
        against money that hasn't actually moved yet."""
        event = _stripe_event()
        event["data"]["object"]["payment_status"] = "unpaid"
        body = json.dumps(event).encode()
        sig = _stripe_signature(body, "whsec_test_secret")
        resp = client.post("/webhooks/stripe", content=body, headers={"Stripe-Signature": sig})
        assert resp.status_code == 200
        assert resp.json().get("ignored") == "payment_pending"
        assert commerce.get_order("cs_test_1") is None

    def test_async_payment_succeeded_ingests_order(self, commerce, client):
        event = _stripe_event(event_type="checkout.session.async_payment_succeeded")
        body = json.dumps(event).encode()
        sig = _stripe_signature(body, "whsec_test_secret")
        resp = client.post("/webhooks/stripe", content=body, headers={"Stripe-Signature": sig})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert commerce.get_order("cs_test_1") is not None

    def test_async_payment_failed_is_a_noop(self, commerce, client):
        event = _stripe_event(event_type="checkout.session.async_payment_failed")
        body = json.dumps(event).encode()
        sig = _stripe_signature(body, "whsec_test_secret")
        resp = client.post("/webhooks/stripe", content=body, headers={"Stripe-Signature": sig})
        assert resp.status_code == 200
        assert commerce.get_order("cs_test_1") is None

    def test_session_expired_is_a_noop(self, commerce, client):
        event = _stripe_event(event_type="checkout.session.expired")
        body = json.dumps(event).encode()
        sig = _stripe_signature(body, "whsec_test_secret")
        resp = client.post("/webhooks/stripe", content=body, headers={"Stripe-Signature": sig})
        assert resp.status_code == 200
        assert commerce.get_order("cs_test_1") is None

    def test_refund_reverses_the_order(self, commerce, client):
        event = _stripe_event()
        event["data"]["object"]["payment_intent"] = "pi_123"
        body = json.dumps(event).encode()
        sig = _stripe_signature(body, "whsec_test_secret")
        client.post("/webhooks/stripe", content=body, headers={"Stripe-Signature": sig})
        assert commerce.get_order("cs_test_1").fulfillment_status == "RECEIVED"

        refund_event = {
            "id": "evt_refund_1", "type": "charge.refunded",
            "data": {"object": {"id": "ch_1", "payment_intent": "pi_123"}},
        }
        refund_body = json.dumps(refund_event).encode()
        refund_sig = _stripe_signature(refund_body, "whsec_test_secret")
        resp = client.post("/webhooks/stripe", content=refund_body,
                           headers={"Stripe-Signature": refund_sig})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert commerce.get_order("cs_test_1").fulfillment_status == "REFUNDED"

    def test_refund_with_no_matching_order_is_a_noop(self, commerce, client):
        refund_event = {
            "id": "evt_refund_2", "type": "charge.refunded",
            "data": {"object": {"id": "ch_2", "payment_intent": "pi_unknown"}},
        }
        body = json.dumps(refund_event).encode()
        sig = _stripe_signature(body, "whsec_test_secret")
        resp = client.post("/webhooks/stripe", content=body, headers={"Stripe-Signature": sig})
        assert resp.status_code == 200
        assert resp.json().get("ignored") == "charge.refunded_no_matching_order"

    def test_processing_failure_returns_500_and_event_not_marked_seen(
        self, commerce, client, monkeypatch
    ):
        """The Tier 1 fix: a transient failure during processing must
        surface as a 500 (so Stripe retries) and must NOT mark the event
        seen — the pre-fix behavior marked it seen first, so a retry after
        a transient failure short-circuited on 'duplicate' and the order
        was silently lost forever despite the customer having paid."""
        import backend.commerce.orders as orders_mod

        monkeypatch.setattr(
            orders_mod, "ingest_order",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("db locked")),
        )
        event = _stripe_event(event_id="evt_crash_1")
        body = json.dumps(event).encode()
        sig = _stripe_signature(body, "whsec_test_secret")
        resp = client.post("/webhooks/stripe", content=body, headers={"Stripe-Signature": sig})
        assert resp.status_code == 500
        assert not commerce.event_already_seen("evt_crash_1")


class TestShopifyWebhook:
    def _order_payload(self):
        return {
            "id": 555,
            "email": "shop@example.com",
            "total_price": "24.50",
            "currency": "USD",
            "customer": {"id": 999, "first_name": "Sam", "last_name": "Buyer"},
            "shipping_address": {"address1": "1 Elm St", "city": "Dallas",
                                 "province": "TX", "zip": "75001", "country": "US"},
            "line_items": [{"sku": "jade-roller", "quantity": 1}],
            "note_attributes": [{"name": "brand_id", "value": "beauty"},
                                {"name": "utm_source", "value": "organic"}],
        }

    def test_missing_secret_returns_503(self, commerce, client, monkeypatch):
        monkeypatch.delenv("SHOPIFY_WEBHOOK_SECRET", raising=False)
        resp = client.post("/webhooks/shopify", content=b"{}",
                           headers={"X-Shopify-Hmac-Sha256": "x"})
        assert resp.status_code == 503

    def test_invalid_signature_rejected(self, commerce, client):
        body = json.dumps(self._order_payload()).encode()
        resp = client.post("/webhooks/shopify", content=body,
                           headers={"X-Shopify-Hmac-Sha256": "bogus=="})
        assert resp.status_code == 400

    def test_valid_signature_ingests_order(self, commerce, client):
        body = json.dumps(self._order_payload()).encode()
        sig = _shopify_signature(body, "shpss_test_secret")
        resp = client.post("/webhooks/shopify", content=body,
                           headers={"X-Shopify-Hmac-Sha256": sig,
                                   "X-Shopify-Topic": "orders/create"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        order = commerce.get_order("555")
        assert order is not None
        assert order.amount == 24.50
        assert order.brand_id == "beauty"

    def test_ignored_topic(self, commerce, client):
        body = json.dumps(self._order_payload()).encode()
        sig = _shopify_signature(body, "shpss_test_secret")
        resp = client.post("/webhooks/shopify", content=body,
                           headers={"X-Shopify-Hmac-Sha256": sig,
                                   "X-Shopify-Topic": "orders/updated"})
        assert resp.json().get("ignored") == "orders/updated"
        assert commerce.get_order("555") is None
