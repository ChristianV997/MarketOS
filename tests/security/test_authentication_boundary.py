"""Comprehensive tests for authentication, role enforcement, and workspace isolation."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api import app
from backend.security.auth import (
    AuthenticatedActor,
    authenticate_token,
    clear_test_tokens,
    register_test_token,
    resolve_authorized_workspace,
)


@pytest.fixture(autouse=True)
def _reset_auth():
    clear_test_tokens()
    yield
    clear_test_tokens()


@pytest.fixture
def client():
    return TestClient(app)


class TestAuthenticationUnit:
    def test_authenticate_token_constant_time(self, monkeypatch):
        monkeypatch.setenv("MARKETOS_OPERATOR_TOKEN", "op_secret_token_12345")
        actor = authenticate_token("op_secret_token_12345")
        assert actor is not None
        assert actor.is_operator is True
        assert actor.role == "operator"
        assert "*" in actor.workspaces

        # Wrong token
        assert authenticate_token("wrong_token") is None
        assert authenticate_token("") is None
        assert authenticate_token(None) is None

    def test_client_tokens_registration_and_workspace_binding(self):
        register_test_token("tok_client_acme", actor_id="client-acme", role="client", workspaces=["acme_corp"])
        actor = authenticate_token("tok_client_acme")
        assert actor is not None
        assert actor.is_operator is False
        assert actor.role == "client"
        assert actor.actor_id == "client-acme"
        assert actor.can_access_workspace("acme_corp") is True
        assert actor.can_access_workspace("other_client") is False

    def test_workspace_binding_resolution(self):
        op = AuthenticatedActor("op1", "operator", frozenset({"*"}))
        assert resolve_authorized_workspace("any_ws", op) == "any_ws"
        assert resolve_authorized_workspace(None, op) == "default"

        client = AuthenticatedActor("c1", "client", frozenset({"client_a"}))
        assert resolve_authorized_workspace("client_a", client) == "client_a"
        assert resolve_authorized_workspace(None, client) == "client_a"

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            resolve_authorized_workspace("forbidden_client", client)
        assert exc.value.status_code == 403


class TestProtectedRoutesAccessControl:
    def test_unauthenticated_operator_route_rejected(self, client, monkeypatch):
        monkeypatch.setenv("MARKETOS_OPERATOR_TOKEN", "op_secret_123")
        monkeypatch.setenv("MARKETOS_AUTH_DISABLED", "false")

        # Control endpoints
        resp = client.post("/control/pause/p1")
        assert resp.status_code in {401, 403}

        # Setup endpoints
        resp = client.get("/api/setup/credentials/status")
        assert resp.status_code in {401, 403}

        # Commerce cycle
        resp = client.post("/commerce/cycle", json={})
        assert resp.status_code in {401, 403}

        # Integrations health
        resp = client.get("/integrations/health")
        assert resp.status_code in {401, 403}

    def test_operator_token_grants_access(self, client, monkeypatch):
        monkeypatch.setenv("MARKETOS_OPERATOR_TOKEN", "op_secret_123")
        headers = {"Authorization": "Bearer op_secret_123"}

        resp = client.post("/control/pause/test_product_1", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "paused"

        resp = client.post("/control/resume/test_product_1", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "resumed"

    def test_client_role_cannot_access_operator_routes(self, client):
        register_test_token("tok_client_restricted", actor_id="client-test", role="client", workspaces=["acme"])
        headers = {"Authorization": "Bearer tok_client_restricted"}

        # Client attempting to pause/control products
        resp = client.post("/control/pause/prod_1", headers=headers)
        assert resp.status_code == 403
        assert "operator_role_required" in resp.json().get("detail", "")

        # Client attempting to read credential status
        resp = client.get("/api/setup/credentials/status", headers=headers)
        assert resp.status_code == 403

        # Client attempting to run commerce cycle
        resp = client.post("/commerce/cycle", json={}, headers=headers)
        assert resp.status_code == 403

    def test_client_access_to_services_with_workspace_binding(self, client):
        register_test_token("tok_client_acme", actor_id="client-acme", role="client", workspaces=["acme"])
        headers = {"Authorization": "Bearer tok_client_acme"}

        # Authorized workspace call succeeds
        resp = client.post(
            "/api/services/unit-economics",
            params={"product": "Widget", "cost": 10.0, "price": 30.0, "workspace": "acme"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("workspace") == "acme"

        # Unauthorized workspace call is blocked with 403
        resp = client.post(
            "/api/services/unit-economics",
            params={"product": "Widget", "cost": 10.0, "price": 30.0, "workspace": "hacked_client"},
            headers=headers,
        )
        assert resp.status_code == 403
        assert "workspace_access_denied" in resp.json().get("detail", "")

    def test_production_mode_fails_closed_without_auth_config(self, client, monkeypatch):
        monkeypatch.setenv("MARKETOS_ENVIRONMENT", "production")
        monkeypatch.delenv("MARKETOS_OPERATOR_TOKEN", raising=False)
        monkeypatch.delenv("MARKETOS_API_KEY", raising=False)
        monkeypatch.delenv("MARKETOS_CLIENT_TOKENS", raising=False)
        monkeypatch.delenv("MARKETOS_CLIENT_TOKEN", raising=False)
        monkeypatch.setenv("MARKETOS_AUTH_DISABLED", "false")

        resp = client.get("/api/setup/credentials/status")
        assert resp.status_code == 503
        assert "authentication_system_unconfigured" in resp.json().get("detail", "")
