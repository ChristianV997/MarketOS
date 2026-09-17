"""Tests for deployment hardening, preflight validation, and health/readiness checks."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api import app
from backend.security.deployment_validation import validate_production_deployment


@pytest.fixture
def client():
    return TestClient(app)


def test_validate_production_deployment_blocked_when_unconfigured():
    env = {
        "MARKETOS_ENVIRONMENT": "production",
    }
    report = validate_production_deployment(env)
    assert report["ready"] is False
    assert report["status"] == "blocked"
    assert "operator_token_required_in_production" in report["blockers"]
    assert any("cors_" in b for b in report["blockers"])


def test_validate_production_deployment_ready_when_configured():
    env = {
        "MARKETOS_ENVIRONMENT": "production",
        "MARKETOS_OPERATOR_TOKEN": "valid_operator_token_12345",
        "ALLOWED_ORIGINS": "https://app.marketos.com",
    }
    report = validate_production_deployment(env)
    assert report["ready"] is True
    assert report["status"] == "ready"
    assert len(report["blockers"]) == 0


def test_health_check_public_read_only(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json().get("ok") is True


def test_ready_check_in_production_fails_closed_when_unconfigured(client, monkeypatch):
    monkeypatch.setenv("MARKETOS_ENVIRONMENT", "production")
    monkeypatch.delenv("MARKETOS_OPERATOR_TOKEN", raising=False)
    monkeypatch.delenv("MARKETOS_API_KEY", raising=False)

    resp = client.get("/ready")
    assert resp.status_code == 503
    data = resp.json()
    assert data.get("ready") is False
    assert "production_security_preflight_failed" in data.get("reason", "")
