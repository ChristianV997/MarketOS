"""Tests for backend.config — credential and configuration management."""
import os
import tempfile
from pathlib import Path

from backend.config import (
    get_credential,
    set_credential,
    is_dry_run,
    get_service_credentials,
    list_configured_services,
    validate_credentials,
)


def test_get_credential_from_env():
    """Credentials from environment variables take precedence."""
    os.environ["TEST_CRED"] = "env_value"
    assert get_credential("TEST_CRED") == "env_value"
    del os.environ["TEST_CRED"]


def test_get_credential_default():
    """Non-existent credential returns default."""
    assert get_credential("NONEXISTENT_CRED", default="default_value") == "default_value"


def test_get_credential_none():
    """Non-existent credential with no default returns None."""
    assert get_credential("NONEXISTENT_CRED") is None


def test_is_dry_run_explicit_false():
    """Explicit META_DRY_RUN=false disables dry-run."""
    os.environ["META_DRY_RUN"] = "false"
    os.environ["META_ACCESS_TOKEN"] = "fake_token"
    os.environ["META_AD_ACCOUNT_ID"] = "fake_account"
    assert is_dry_run("meta") is False
    del os.environ["META_DRY_RUN"]
    del os.environ["META_ACCESS_TOKEN"]
    del os.environ["META_AD_ACCOUNT_ID"]


def test_is_dry_run_explicit_true():
    """Explicit META_DRY_RUN=true enables dry-run regardless of credentials."""
    os.environ["META_DRY_RUN"] = "true"
    os.environ["META_ACCESS_TOKEN"] = "fake_token"
    os.environ["META_AD_ACCOUNT_ID"] = "fake_account"
    assert is_dry_run("meta") is True
    del os.environ["META_DRY_RUN"]
    del os.environ["META_ACCESS_TOKEN"]
    del os.environ["META_AD_ACCOUNT_ID"]


def test_is_dry_run_missing_credentials():
    """Dry-run mode when credentials are missing."""
    # Remove credentials if they exist
    for key in ["META_DRY_RUN", "META_ACCESS_TOKEN", "META_AD_ACCOUNT_ID"]:
        os.environ.pop(key, None)

    # Should default to dry-run when no credentials
    assert is_dry_run("meta") is True


def test_get_service_credentials_partial():
    """get_service_credentials returns only available credentials."""
    os.environ["META_ACCESS_TOKEN"] = "token"
    # META_AD_ACCOUNT_ID is not set
    os.environ.pop("META_AD_ACCOUNT_ID", None)

    creds = get_service_credentials("meta")
    assert "META_ACCESS_TOKEN" in creds
    assert "META_AD_ACCOUNT_ID" not in creds

    del os.environ["META_ACCESS_TOKEN"]


def test_validate_credentials_missing():
    """validate_credentials detects missing required fields."""
    os.environ.pop("META_ACCESS_TOKEN", None)
    os.environ.pop("META_AD_ACCOUNT_ID", None)

    is_valid, msg = validate_credentials("meta")
    assert is_valid is False
    assert "Missing" in msg


def test_validate_credentials_present():
    """validate_credentials passes when all required fields present."""
    os.environ["META_ACCESS_TOKEN"] = "token"
    os.environ["META_AD_ACCOUNT_ID"] = "account"

    is_valid, msg = validate_credentials("meta")
    assert is_valid is True
    assert "All" in msg

    del os.environ["META_ACCESS_TOKEN"]
    del os.environ["META_AD_ACCOUNT_ID"]


def test_list_configured_services():
    """list_configured_services shows status of all services."""
    # Reset all credentials
    for key in ["META_ACCESS_TOKEN", "META_AD_ACCOUNT_ID",
                "TIKTOK_ACCESS_TOKEN", "TIKTOK_ADVERTISER_ID"]:
        os.environ.pop(key, None)

    services = list_configured_services()
    assert "meta" in services
    assert "tiktok" in services
    # Should all be False (no credentials set)
    assert services["meta"] is False
    assert services["tiktok"] is False
