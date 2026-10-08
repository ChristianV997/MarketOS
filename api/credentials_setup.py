"""api.credentials_setup — REST API for credential management and setup.

Provides a secure interface for users to add/update API credentials without
exposing them in logs or terminal history.

Usage:
  POST /api/setup/credentials/set    (set a credential)
  GET /api/setup/credentials/status  (view which services are configured)
  GET /api/setup/instructions        (view setup instructions)
"""
import logging

from fastapi import APIRouter, Body, Depends, HTTPException

from backend.identity.http import require_workspace_permission
from backend.identity.repository import CLIENT_TYPE
from backend.identity.roles import CREDENTIAL_WRITE
from backend.identity.workspaces import WorkspaceAccess

_log = logging.getLogger(__name__)

router = APIRouter()

_MAX_VALUE_LEN = 4096
_write_gate = require_workspace_permission(CLIENT_TYPE, CREDENTIAL_WRITE)


def _allowed_keys() -> frozenset[str]:
    """Only provider credential keys; never ``*_DRY_RUN`` flags or arbitrary names."""
    from backend.config import _SERVICE_CREDENTIALS

    return frozenset(k for keys in _SERVICE_CREDENTIALS.values() for k in keys)


@router.post("/credentials/set")
async def set_credential(
    key: str = Body(...),
    value: str = Body(...),
    _access: WorkspaceAccess = Depends(_write_gate),
) -> dict:
    """Securely set a credential (verified internal operator only).

    Args:
      key: Credential key (e.g., META_ACCESS_TOKEN)
      value: Credential value (stored locally, never logged)

    Returns:
      {status, message}

    Security notes:
      - Credential value is NOT logged
      - Stored in ~/.marketos/credentials.json with 0o600 permissions
      - Only your user can read it
    """
    if key not in _allowed_keys():
        raise HTTPException(status_code=400, detail="Unsupported credential key")
    if not value or len(value) > _MAX_VALUE_LEN or any(c in value for c in "\r\n\x00"):
        raise HTTPException(status_code=400, detail="Invalid credential value")

    try:
        from backend.config import set_credential
        set_credential(key, value)
        _log.info("credential_set key=%s", key)  # Log key but NOT value
        return {
            "status": "ok",
            "message": f"Credential {key} saved successfully",
        }
    except Exception as exc:
        _log.error("failed_to_set_credential key=%s error_type=%s", key, type(exc).__name__)
        raise HTTPException(status_code=500, detail="Failed to store credential")


@router.get("/credentials/status")
async def credentials_status() -> dict:
    """Check which services are configured."""
    try:
        from backend.config import list_configured_services, get_service_credentials

        services = list_configured_services()
        details = {}

        for service, is_ready in services.items():
            details[service] = {
                "configured": is_ready,
                "has_credentials": bool(get_service_credentials(service)),
            }

        return {
            "status": "ok",
            "services": details,
            "services_ready": sum(1 for ready in services.values() if ready),
            "services_total": len(services),
        }
    except Exception as exc:
        _log.error("failed_to_get_status error=%s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/instructions/{service}")
async def setup_instructions(service: str) -> dict:
    """Get setup instructions for a specific service."""
    instructions = {
        "meta": {
            "name": "Meta Ads",
            "steps": [
                "Go to https://developers.facebook.com/apps/",
                "Create or select your app",
                "Go to Settings > Basic to get your App ID and Secret",
                "Use Tools > Access Token Generator (Ads section) to get token",
                "Go to Ads Manager and copy your Ad Account ID",
                "Set META_ACCESS_TOKEN and META_AD_ACCOUNT_ID",
            ],
            "sandbox": "Use a Test Ad Account for sandboxed testing (no real spend)",
            "credentials": [
                "META_ACCESS_TOKEN",
                "META_AD_ACCOUNT_ID",
            ],
        },
        "tiktok": {
            "name": "TikTok Ads",
            "steps": [
                "Go to https://business.tiktok.com/",
                "Create or sign into your business account",
                "Navigate to Settings > API Access",
                "Request API access if not already approved",
                "Create an application",
                "Copy your Access Token and Advertiser ID",
            ],
            "sandbox": "Create a test campaign with $0 daily budget",
            "credentials": [
                "TIKTOK_ACCESS_TOKEN",
                "TIKTOK_ADVERTISER_ID",
            ],
        },
        "shopify": {
            "name": "Shopify",
            "steps": [
                "Go to https://www.shopify.com/",
                "Create a development store or sign into your store",
                "Go to Settings > Apps and channels",
                "Create a custom app (e.g., 'MarketOS')",
                "Set permissions: 'Products' (read, write), 'Orders' (read)",
                "Install and copy the Admin API access token",
                "Your store URL is in Settings > Domains",
            ],
            "sandbox": "Use a development store (free, no real products)",
            "credentials": [
                "SHOPIFY_STORE_URL",
                "SHOPIFY_ACCESS_TOKEN",
            ],
        },
    }

    if service.lower() not in instructions:
        raise HTTPException(status_code=404, detail=f"Unknown service: {service}")

    return {
        "status": "ok",
        "service": service.lower(),
        **instructions[service.lower()],
    }


@router.get("/instructions")
async def all_instructions() -> dict:
    """Get setup instructions for all services."""
    instructions = {
        "meta": {
            "name": "Meta Ads",
            "url": "https://developers.facebook.com/apps/",
            "required_credentials": ["META_ACCESS_TOKEN", "META_AD_ACCOUNT_ID"],
        },
        "tiktok": {
            "name": "TikTok Ads",
            "url": "https://business.tiktok.com/",
            "required_credentials": ["TIKTOK_ACCESS_TOKEN", "TIKTOK_ADVERTISER_ID"],
        },
        "shopify": {
            "name": "Shopify",
            "url": "https://www.shopify.com/",
            "required_credentials": ["SHOPIFY_STORE_URL", "SHOPIFY_ACCESS_TOKEN"],
        },
    }

    return {
        "status": "ok",
        "services": instructions,
        "setup_flow": [
            "1. Choose a service (Meta, TikTok, or Shopify)",
            "2. Follow the setup instructions for that service",
            "3. Copy the required credentials",
            "4. Call POST /api/setup/credentials/set for each credential",
            "5. Verify with GET /api/setup/credentials/status",
        ],
    }


_TEST_SERVICES = ("meta", "tiktok", "shopify")


async def run_service_test(service: str) -> dict:
    """Offline-only credential check; never calls a provider.

    No server-side approval seam exists for live provider actions (the cockpit
    approval store is unauthenticated, the Approval Ledger is an offline record),
    so a service that would go live is reported ``blocked`` instead of exercised.
    Also used directly by ``api/onboarding.py``.
    """
    from backend.config import is_dry_run

    service = service.lower()
    if service not in _TEST_SERVICES:
        raise HTTPException(status_code=404, detail="Unknown service")
    if is_dry_run(service):
        return {
            "status": "dry_run",
            "message": f"{service} is in dry-run mode (no credentials detected)",
        }
    return {
        "status": "blocked",
        "message": "Live provider tests are disabled: no approval mechanism is available",
    }


@router.post("/test/{service}")
async def test_credentials_route(
    service: str,
    _access: WorkspaceAccess = Depends(_write_gate),
) -> dict:
    """Offline credential-readiness check (verified internal operator only)."""
    return await run_service_test(service)


# api/onboarding.py imports this name; it is the same offline-only helper.
test_credentials = run_service_test

__all__ = ["router", "run_service_test"]
