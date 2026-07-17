"""api.credentials_setup — REST API for credential management and setup.

Provides a secure interface for users to add/update API credentials without
exposing them in logs or terminal history.

Usage:
  POST /api/setup/credentials/set    (set a credential)
  GET /api/setup/credentials/status  (view which services are configured)
  GET /api/setup/instructions        (view setup instructions)
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Body

_log = logging.getLogger(__name__)

router = APIRouter()


@router.post("/credentials/set")
async def set_credential(
    key: str = Body(...),
    value: str = Body(...),
) -> dict:
    """Securely set a credential.

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
    # Validate key format
    if not key or not value:
        raise HTTPException(status_code=400, detail="Key and value required")

    if not key.isupper() or not key.replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="Invalid key format")

    try:
        from backend.config import set_credential
        set_credential(key, value)
        _log.info("credential_set key=%s", key)  # Log key but NOT value
        return {
            "status": "ok",
            "message": f"Credential {key} saved successfully",
        }
    except Exception as exc:
        _log.error("failed_to_set_credential key=%s error=%s", key, exc)
        raise HTTPException(status_code=500, detail=str(exc))


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
                "Install and copy your API Key and Password",
                "Your store URL is in Settings > Domains",
            ],
            "sandbox": "Use a development store (free, no real products)",
            "credentials": [
                "SHOPIFY_STORE_URL",
                "SHOPIFY_API_KEY",
                "SHOPIFY_API_PASSWORD",
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
            "required_credentials": ["SHOPIFY_STORE_URL", "SHOPIFY_API_KEY", "SHOPIFY_API_PASSWORD"],
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


@router.post("/test/{service}")
async def test_credentials(service: str) -> dict:
    """Test if credentials for a service are valid.

    Makes a minimal API call to verify credentials work.
    """
    service = service.lower()

    if service == "meta":
        try:
            from backend.integrations import meta_ads_client
            from backend.config import is_dry_run

            if is_dry_run("meta"):
                return {
                    "status": "dry_run",
                    "message": "Meta is in dry-run mode (no credentials detected)",
                }

            # Try to create a test campaign
            campaign_id = meta_ads_client.create_campaign("__TEST__Campaign__")
            if campaign_id and campaign_id.startswith("dry_") is False:
                return {
                    "status": "ok",
                    "message": "Meta credentials are valid",
                    "campaign_id": campaign_id,
                }
            else:
                return {
                    "status": "error",
                    "message": "Failed to create test campaign",
                }
        except Exception as exc:
            return {
                "status": "error",
                "message": str(exc),
            }

    elif service == "tiktok":
        try:
            from backend.config import is_dry_run
            from backend.integrations import tiktok_ads

            if is_dry_run("tiktok"):
                return {
                    "status": "dry_run",
                    "message": "TikTok is in dry-run mode (no credentials detected)",
                }

            campaign_id = tiktok_ads.create_campaign("__TEST__Campaign__", daily_budget=1.0)
            if campaign_id and not str(campaign_id).startswith("dry"):
                return {
                    "status": "ok",
                    "message": "TikTok credentials are valid",
                    "campaign_id": str(campaign_id),
                }
            else:
                return {
                    "status": "error",
                    "message": "Failed to create test campaign",
                }
        except Exception as exc:
            _log.exception("tiktok_test_failed")
            return {
                "status": "error",
                "message": str(exc),
            }

    elif service == "shopify":
        try:
            from backend.config import is_dry_run
            from backend.creation.store_builder import create_product_page

            if is_dry_run("shopify"):
                return {
                    "status": "dry_run",
                    "message": "Shopify is in dry-run mode (no credentials detected)",
                }

            page = create_product_page(
                "__TEST__Product__",
                "<p>Test product for credential verification</p>",
                1.0
            )
            if page.get("status") == "ok" and page.get("dry_run") is not True:
                return {
                    "status": "ok",
                    "message": "Shopify credentials are valid",
                    "product_id": page.get("product_id"),
                }
            else:
                return {
                    "status": "error",
                    "message": "Failed to create test product",
                }
        except Exception as exc:
            _log.exception("shopify_test_failed")
            return {
                "status": "error",
                "message": str(exc),
            }

    else:
        raise HTTPException(status_code=404, detail=f"Unknown service: {service}")


__all__ = ["router"]
