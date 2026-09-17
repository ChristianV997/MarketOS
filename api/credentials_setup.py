"""api.credentials_setup — REST API for credential management and setup.

Provides a secure, authenticated interface for operators to add/update API credentials without
exposing them in logs, frontend bundles, or unauthenticated endpoints.

Usage:
  POST /api/setup/credentials/set    (operator-authenticated: set a credential)
  GET /api/setup/credentials/status  (operator-authenticated: view which services are configured)
  GET /api/setup/instructions        (public: view setup instructions)
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from backend.security.auth import AuthenticatedActor, require_operator
from backend.security.credentials import (
    diagnose_credential_safety,
    is_valid_credential_key,
    mask_secret,
)

_log = logging.getLogger(__name__)

router = APIRouter()


@router.post("/credentials/set")
async def set_credential(
    key: str = Body(...),
    value: str = Body(...),
    actor: AuthenticatedActor = Depends(require_operator),
) -> dict[str, Any]:
    """Securely set a credential with operator authorization and strict key validation.

    Args:
      key: Credential key (must be an approved uppercase service key, e.g., META_ACCESS_TOKEN)
      value: Credential value (stored securely, never logged or echoed)
      actor: Authenticated operator actor
    """
    clean_key = (key or "").strip()
    clean_val = (value or "").strip()

    if not clean_key or not clean_val:
        raise HTTPException(status_code=400, detail="Key and value required")

    if not is_valid_credential_key(clean_key):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid or unapproved credential key '{clean_key}'. Key must be in recognized service list.",
        )

    try:
        from backend.config import set_credential as store_cred

        store_cred(clean_key, clean_val)
        _log.info(
            "operator_credential_set actor=%s key=%s length=%d",
            actor.actor_id,
            clean_key,
            len(clean_val),
        )
        return {
            "status": "ok",
            "message": f"Credential {clean_key} saved successfully",
            "key": clean_key,
            "masked": mask_secret(clean_val),
        }
    except Exception as exc:
        _log.error("failed_to_set_credential key=%s error=%s", clean_key, exc)
        raise HTTPException(status_code=500, detail="failed_to_store_credential")


@router.get("/credentials/status")
async def credentials_status(
    actor: AuthenticatedActor = Depends(require_operator),
) -> dict[str, Any]:
    """Check which services are configured. Operator authentication required; values are masked."""
    try:
        from backend.config import get_service_credentials, list_configured_services

        services = list_configured_services()
        details = {}

        for service, is_ready in services.items():
            creds = get_service_credentials(service)
            details[service] = {
                "configured": is_ready,
                "has_credentials": bool(creds),
                "configured_keys": list(creds.keys()),
            }

        diag = diagnose_credential_safety()

        return {
            "status": "ok",
            "operator": actor.actor_id,
            "services": details,
            "services_ready": sum(1 for ready in services.values() if ready),
            "services_total": len(services),
            "storage_mode": diag.get("storage_mode", "unknown"),
        }
    except Exception as exc:
        _log.error("failed_to_get_status error=%s", exc)
        raise HTTPException(status_code=500, detail="failed_to_retrieve_credential_status")


@router.get("/instructions/{service}")
async def setup_instructions(service: str) -> dict[str, Any]:
    """Get setup instructions for a specific service (public documentation)."""
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
async def all_instructions() -> dict[str, Any]:
    """Get setup instructions for all services (public documentation)."""
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


@router.post("/test/{service}")
async def test_credentials(
    service: str,
    actor: AuthenticatedActor = Depends(require_operator),
) -> dict[str, Any]:
    """Test service configuration in dry-run mode. Operator authentication required."""
    service = service.lower()

    if service == "meta":
        try:
            from backend.config import is_dry_run
            from backend.integrations import meta_ads_client

            if is_dry_run("meta"):
                return {
                    "status": "dry_run",
                    "message": "Meta is in dry-run mode (no credentials detected or dry-run active)",
                }

            campaign_id = meta_ads_client.create_campaign("__TEST__Campaign__")
            if campaign_id:
                return {
                    "status": "ok",
                    "message": "Meta credentials verified",
                    "campaign_id": campaign_id,
                }
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
                    "message": "TikTok is in dry-run mode (no credentials detected or dry-run active)",
                }

            campaign_id = tiktok_ads.create_campaign("__TEST__Campaign__", budget=1.0)
            if campaign_id:
                return {
                    "status": "ok",
                    "message": "TikTok credentials verified",
                    "campaign_id": str(campaign_id),
                }
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
                    "message": "Shopify is in dry-run mode (no credentials detected or dry-run active)",
                }

            page = create_product_page(
                "__TEST__Product__",
                "<p>Test product for credential verification</p>",
                1.0,
            )
            if page.get("status") == "ok":
                return {
                    "status": "ok",
                    "message": "Shopify credentials verified",
                    "product_id": page.get("product_id"),
                }
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
