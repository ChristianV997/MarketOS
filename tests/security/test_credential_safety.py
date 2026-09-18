"""Tests for credential safety, masking, key allowlisting, and diagnostics."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api import app
from backend.security.auth import register_test_token
from backend.security.credentials import (
    diagnose_credential_safety,
    is_token_shaped,
    is_valid_credential_key,
    mask_secret,
)


@pytest.fixture
def client():
    return TestClient(app)


def test_mask_secret():
    assert mask_secret("") == ""
    assert mask_secret(None) == ""
    assert mask_secret("short") == "********"
    assert mask_secret("12345678") == "********"
    masked = mask_secret("sk_live_1234567890abcdef")
    assert masked == "sk_l...cdef"
    assert "1234567890" not in masked


def test_is_valid_credential_key():
    assert is_valid_credential_key("META_ACCESS_TOKEN") is True
    assert is_valid_credential_key("STRIPE_SECRET_KEY") is True
    assert is_valid_credential_key("SHOPIFY_ACCESS_TOKEN") is True
    assert is_valid_credential_key("CJ_API_KEY") is True

    # Invalid keys
    assert is_valid_credential_key("meta_access_token") is False  # lowercase
    assert is_valid_credential_key("UNKNOWN_ARBITRARY_KEY") is False
    assert is_valid_credential_key("../path/traversal") is False
    assert is_valid_credential_key("AWS_SECRET_ACCESS_KEY") is False  # unapproved arbitrary


def test_is_token_shaped():
    assert is_token_shaped("Bearer sk_live_12345678901234567890") is True
    assert is_token_shaped("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.t-IDcSemACt8x4iTMCda8Yhe3iZaWbvV5XKSTbuAn0M") is True
    assert is_token_shaped("simple_word") is False
    assert is_token_shaped("") is False
    assert is_token_shaped(None) is False


def test_diagnose_credential_safety_never_exposes_raw_secrets():
    env = {
        "META_ACCESS_TOKEN": "EAABsbcs748392010203040506070809",
        "STRIPE_SECRET_KEY": "sk_live_9999988888777776666655555",
    }
    diag = diagnose_credential_safety(env)
    assert diag["raw_values_exposed"] is False
    assert diag["configured_key_count"] == 2
    assert "META_ACCESS_TOKEN" in diag["configured_keys"]
    assert "STRIPE_SECRET_KEY" in diag["configured_keys"]

    # Verify preview is masked
    meta_diag = diag["masked_status"]["META_ACCESS_TOKEN"]
    assert meta_diag["present"] is True
    assert "EAAB...0809" in meta_diag["preview"]
    assert "92010203" not in meta_diag["preview"]


def test_credential_set_api_boundary(client):
    register_test_token("tok_op", actor_id="operator", role="operator")
    headers = {"Authorization": "Bearer tok_op"}

    # Attempting unapproved key
    resp = client.post(
        "/api/setup/credentials/set",
        json={"key": "UNAPPROVED_KEY_FOO", "value": "some_secret_123"},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "Invalid or unapproved credential key" in resp.json().get("detail", "")

    # Valid key
    resp = client.post(
        "/api/setup/credentials/set",
        json={"key": "SHOPIFY_ACCESS_TOKEN", "value": "shpat_1234567890abcdef"},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["key"] == "SHOPIFY_ACCESS_TOKEN"
    assert data["masked"] == "shpa...cdef"
    assert "1234567890" not in data["masked"]


def test_credential_test_endpoint_dry_run_and_fail_closed(client):
    register_test_token("tok_op", actor_id="operator", role="operator")
    headers = {"Authorization": "Bearer tok_op"}

    # In dry-run mode (default), returns dry-run status without provider mutations
    resp = client.post("/api/setup/test/meta", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in {"dry_run", "ok", "blocked"}
    if data["status"] == "blocked":
        assert "reasons" in data

    # Unknown service
    resp_unknown = client.post("/api/setup/test/unknown_service", headers=headers)
    assert resp_unknown.status_code == 404
