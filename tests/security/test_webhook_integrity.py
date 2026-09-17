"""Tests for webhook integrity, bounded payload size, signature verification, and idempotency."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import pytest
from fastapi.testclient import TestClient

from backend.api import app
from backend.security.webhooks import (
    MAX_WEBHOOK_PAYLOAD_BYTES,
    get_webhook_ledger,
    verify_generic_hmac,
    verify_shopify_signature,
    verify_stripe_signature,
)


@pytest.fixture(autouse=True)
def _reset_ledger():
    get_webhook_ledger().clear()
    yield
    get_webhook_ledger().clear()


@pytest.fixture
def client():
    return TestClient(app)


def test_verify_stripe_signature_constant_time():
    test_signing_key = "whsec_test_secret"
    body = b'{"id":"evt_1","type":"test"}'
    ts = int(time.time())
    sig = hmac.new(test_signing_key.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    header = f"t={ts},v1={sig}"

    assert verify_stripe_signature(body, header, test_signing_key) is True
    assert verify_stripe_signature(body, f"t={ts},v1=wrong_sig", test_signing_key) is False
    assert verify_stripe_signature(b"altered_body", header, test_signing_key) is False

    # Timestamp out of tolerance
    old_ts = ts - 400
    old_sig = hmac.new(test_signing_key.encode(), f"{old_ts}.".encode() + body, hashlib.sha256).hexdigest()
    old_header = f"t={old_ts},v1={old_sig}"
    assert verify_stripe_signature(body, old_header, test_signing_key, tolerance_seconds=300) is False


def test_verify_shopify_signature_constant_time():
    test_signing_key = "shpss_test_secret"
    body = b'{"id":12345,"note_attributes":[]}'
    digest = hmac.new(test_signing_key.encode(), body, hashlib.sha256).digest()
    sig = base64.b64encode(digest).decode()

    assert verify_shopify_signature(body, sig, test_signing_key) is True
    assert verify_shopify_signature(body, "bad_sig", test_signing_key) is False
    assert verify_shopify_signature(b"altered", sig, test_signing_key) is False


def test_verify_generic_hmac():
    test_signing_key = "cj_secret_123"
    body = b'{"orderId":"cj_1234"}'
    sig = hmac.new(test_signing_key.encode(), body, hashlib.sha256).hexdigest()

    assert verify_generic_hmac(body, sig, test_signing_key) is True
    assert verify_generic_hmac(body, f"sha256={sig}", test_signing_key) is True
    assert verify_generic_hmac(body, "wrong_sig", test_signing_key) is False


def test_webhook_payload_size_limit_rejection(client, monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test_secret")

    oversized_body = b"x" * (MAX_WEBHOOK_PAYLOAD_BYTES + 1024)
    resp = client.post(
        "/webhooks/stripe",
        content=oversized_body,
        headers={"Stripe-Signature": "t=1,v1=fake"},
    )
    assert resp.status_code == 413
    assert "payload_too_large" in resp.json().get("detail", "")


def test_cj_webhook_flow_and_idempotency(client, monkeypatch):
    test_signing_key = "cj_secret_test"
    monkeypatch.setenv("CJ_WEBHOOK_SECRET", test_signing_key)

    payload = {"orderId": "cj_order_999", "status": "SHIPPED", "trackingNumber": "TRK12345"}
    body = json.dumps(payload).encode()
    sig = hmac.new(test_signing_key.encode(), body, hashlib.sha256).hexdigest()

    # First delivery: accepted
    resp = client.post(
        "/webhooks/cj",
        content=body,
        headers={"X-CJ-Signature": sig},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json().get("duplicate") is not True

    # Repeated delivery: duplicate caught and idempotent
    resp_dupe = client.post(
        "/webhooks/cj",
        content=body,
        headers={"X-CJ-Signature": sig},
    )
    assert resp_dupe.status_code == 200
    assert resp_dupe.json()["status"] == "ok"
    assert resp_dupe.json().get("duplicate") is True
