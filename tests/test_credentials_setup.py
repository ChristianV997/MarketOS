"""Tests for credential management and verification."""
import json
import os
import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.credentials_setup import router as credentials_router
from backend.config import get_credential, set_credential, list_configured_services, is_dry_run


@pytest.fixture
def temp_config(monkeypatch):
    """Use temporary config file for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "credentials.json"
        monkeypatch.setenv("MARKETOS_CONFIG_PATH", str(config_path))
        yield config_path


@pytest.fixture
def client(temp_config):
    """FastAPI test client with credentials router."""
    app = FastAPI()
    app.include_router(credentials_router, prefix="/api/setup")
    return TestClient(app)


class TestCredentialStorage:
    """Test local credential storage."""

    def test_set_and_get_credential(self, temp_config):
        """Test setting and retrieving a credential."""
        set_credential("TEST_TOKEN", "secret123")
        assert get_credential("TEST_TOKEN") == "secret123"

    def test_env_takes_precedence(self, temp_config, monkeypatch):
        """Environment variable takes precedence over config file."""
        set_credential("TEST_KEY", "file_value")
        monkeypatch.setenv("TEST_KEY", "env_value")
        assert get_credential("TEST_KEY") == "env_value"

    def test_default_value(self, temp_config):
        """Return default when credential not found."""
        assert get_credential("NONEXISTENT", default="default_val") == "default_val"
        assert get_credential("NONEXISTENT") is None

    def test_config_persistence(self, temp_config):
        """Credentials persist across calls."""
        set_credential("KEY1", "value1")
        set_credential("KEY2", "value2")

        # New instance should still find them
        assert get_credential("KEY1") == "value1"
        assert get_credential("KEY2") == "value2"

    def test_config_file_permissions(self, temp_config):
        """Config file has restricted permissions."""
        set_credential("SECRET", "value")
        # Should be readable only by owner (0o600)
        if temp_config.exists():
            mode = temp_config.stat().st_mode & 0o777
            assert mode == 0o600


class TestDryRunLogic:
    """Test dry-run detection."""

    def test_dry_run_explicit_false_with_credentials(self, temp_config, monkeypatch):
        """Live mode when explicit false + credentials present."""
        set_credential("META_ACCESS_TOKEN", "token123")
        set_credential("META_AD_ACCOUNT_ID", "act_123")
        monkeypatch.setenv("META_DRY_RUN", "false")
        assert is_dry_run("meta") is False

    def test_dry_run_explicit_true_ignores_credentials(self, temp_config, monkeypatch):
        """Dry-run when explicit true, even with credentials."""
        set_credential("META_ACCESS_TOKEN", "token123")
        set_credential("META_AD_ACCOUNT_ID", "act_123")
        monkeypatch.setenv("META_DRY_RUN", "true")
        assert is_dry_run("meta") is True

    def test_dry_run_case_insensitive(self, temp_config, monkeypatch):
        """Case-insensitive dry-run check."""
        set_credential("META_ACCESS_TOKEN", "token123")
        set_credential("META_AD_ACCOUNT_ID", "act_123")
        monkeypatch.setenv("META_DRY_RUN", "FALSE")
        assert is_dry_run("meta") is False
        monkeypatch.setenv("META_DRY_RUN", "TRUE")
        assert is_dry_run("meta") is True


class TestCredentialsAPI:
    """Test REST API endpoints."""

    def test_set_credential_endpoint(self, client, temp_config):
        """POST /credentials/set stores credential."""
        response = client.post(
            "/api/setup/credentials/set",
            json={"key": "TEST_TOKEN", "value": "secret123"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert get_credential("TEST_TOKEN") == "secret123"

    def test_set_credential_invalid_key(self, client, temp_config):
        """Invalid key format rejected."""
        response = client.post(
            "/api/setup/credentials/set",
            json={"key": "invalid-key", "value": "value"},
        )
        assert response.status_code == 400

    def test_set_credential_missing_value(self, client, temp_config):
        """Missing value rejected."""
        response = client.post(
            "/api/setup/credentials/set",
            json={"key": "TEST_KEY"},
        )
        assert response.status_code == 422  # Validation error

    def test_credentials_status_endpoint(self, client, temp_config):
        """GET /credentials/status shows configuration."""
        set_credential("META_ACCESS_TOKEN", "token123")
        set_credential("META_AD_ACCOUNT_ID", "act_123")

        response = client.get("/api/setup/credentials/status")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "services" in data
        assert "meta" in data["services"]

    def test_setup_instructions_meta(self, client):
        """GET /setup/instructions/meta returns steps."""
        response = client.get("/api/setup/instructions/meta")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "meta"
        assert "steps" in data
        assert len(data["steps"]) > 0

    def test_setup_instructions_all(self, client):
        """GET /setup/instructions returns all services."""
        response = client.get("/api/setup/instructions")
        assert response.status_code == 200
        data = response.json()
        assert "services" in data
        assert "meta" in data["services"]
        assert "tiktok" in data["services"]
        assert "shopify" in data["services"]

    def test_test_credentials_unknown_service(self, client):
        """Unknown service returns 404."""
        response = client.post("/api/setup/test/unknown_service")
        assert response.status_code == 404


class TestServiceConfigurationStatus:
    """Test service configuration detection."""

    def test_list_configured_services_meta(self, temp_config, monkeypatch):
        """Meta marked ready when credentials + not dry-run."""
        set_credential("META_ACCESS_TOKEN", "token123")
        set_credential("META_AD_ACCOUNT_ID", "act_123")
        monkeypatch.setenv("META_DRY_RUN", "false")

        services = list_configured_services()
        assert services["meta"] is True
        assert services.get("tiktok") is False

    def test_validate_credentials_present(self, temp_config):
        """Validation passes when all credentials present."""
        from backend.config import validate_credentials

        set_credential("META_ACCESS_TOKEN", "token123")
        set_credential("META_AD_ACCOUNT_ID", "act_123")

        is_valid, msg = validate_credentials("meta")
        assert is_valid is True
        assert "All credentials" in msg
