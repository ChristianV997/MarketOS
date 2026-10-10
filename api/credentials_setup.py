"""api.credentials_setup — REST API for credential management and setup.

Provides an interface for a verified internal operator to add/update API credentials
without exposing them in logs or terminal history.

Usage:
  POST /api/setup/credentials/set    (set a credential; verified internal operator only)
  POST /api/setup/test/{service}     (report a service's mode; verified internal operator only)
  GET /api/setup/credentials/status  (view which services are configured)
  GET /api/setup/instructions        (view setup instructions)

Authorization contract: the two POST routes depend on
``backend.identity.http.require_workspace_permission`` for the principal's sole internal
workspace, so the caller is identified by a verified token and a server-side membership role
only. Nothing in the body, query, or other headers can authorize a request, and a body that
carries a caller, workspace, or role field is rejected. The gates run before the handler
reads a byte of the body (the body is read here, not by FastAPI), so an unauthenticated or
unauthorized caller reaches neither the parser, credential storage, nor a provider helper.
Until deployment wiring supplies the token verifier and workspace repository (see
docs/IDENTITY_WORKSPACE_FOUNDATION.md) both routes fail closed with 401/503.

Provider actions are default-off: the test route never calls a provider helper. A service in
live mode reports ``blocked`` because no server-side approval seam exists yet; the Approval
Ledger (``evaluation.companyos.approval_ledger``) remains the gate for any future live action.

Error bodies are a fixed ``{code, field}``: they never echo the submitted key, value, field
names, service name, exception text, or a path.
"""
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from backend.identity.http import require_workspace_permission
from backend.identity.repository import OWNER_TYPE
from backend.identity.roles import CREDENTIAL_TEST, CREDENTIAL_WRITE
from backend.identity.workspaces import WorkspaceAccess

_log = logging.getLogger(__name__)

router = APIRouter()

credential_write_gate = require_workspace_permission(OWNER_TYPE, CREDENTIAL_WRITE)
credential_test_gate = require_workspace_permission(OWNER_TYPE, CREDENTIAL_TEST)

MAX_BODY_BYTES = 16 * 1024  # a credential value is at most 4096 characters; the rest is JSON framing
_MAX_VALUE_LENGTH = 4096
_TESTABLE_SERVICES = ("meta", "tiktok", "shopify")
# Fields that name a caller, workspace, or role. They never authorize anything on these routes, so a
# body that carries one is rejected instead of silently ignored: a client must not believe it was honored.
_IDENTITY_FIELDS = frozenset(
    {
        "actor", "actor_id", "admin", "is_admin", "issuer", "operator", "org_id", "organization_id",
        "permissions", "role", "roles", "subject", "tenant", "tenant_id", "user", "user_id",
        "workspace", "workspace_id", "workspace_name",
    }
)


def stable_error(status_code: int, code: str, field: str | None = None) -> HTTPException:
    """An error whose body is a fixed code and a known field name, never caller input."""
    return HTTPException(status_code=status_code, detail={"code": code, "field": field})


async def read_bounded_json_object(request: Request, fields: frozenset[str]) -> dict[str, Any]:
    """Read the request body as one JSON object whose keys are all in ``fields``.

    Call this only after the route's authorization gates have run: they are route dependencies, so
    FastAPI has already resolved them, and a denied caller's body is never read. The body is capped at
    ``MAX_BODY_BYTES`` while streaming. Every rejection is a stable code that does not echo input.
    """
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise stable_error(415, "unsupported_media_type")
    declared = request.headers.get("content-length")
    if declared is not None and declared.isascii() and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise stable_error(413, "payload_too_large")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            raise stable_error(413, "payload_too_large")
        chunks.append(chunk)
    try:
        body = json.loads(b"".join(chunks))
    except (ValueError, RecursionError):
        raise stable_error(422, "invalid_json") from None
    if not isinstance(body, dict):
        raise stable_error(422, "invalid_body")
    names = {str(name).strip().lower().replace("-", "_") for name in body}
    if names & _IDENTITY_FIELDS:
        raise stable_error(422, "identity_field_rejected")
    if any(name not in fields for name in body):
        raise stable_error(422, "unknown_field")
    return body


def required_string(body: dict[str, Any], field: str) -> str:
    """The named body field as a string, or a stable 422 that does not echo the submitted value."""
    if field not in body:
        raise stable_error(422, "missing_field", field)
    value = body[field]
    if not isinstance(value, str):
        raise stable_error(422, "invalid_type", field)
    return value


def _allowed_credential_keys() -> frozenset[str]:
    """Only provider credential keys; never ``*_DRY_RUN`` flags or arbitrary environment names."""
    from backend.config import _SERVICE_CREDENTIALS

    return frozenset(key for keys in _SERVICE_CREDENTIALS.values() for key in keys)


def validate_credential_input(key: str, value: str) -> None:
    """Raise a stable 400 for a key outside the provider allowlist or a malformed value."""
    if key not in _allowed_credential_keys():
        raise stable_error(400, "unsupported_key", "key")
    if not value or len(value) > _MAX_VALUE_LENGTH or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise stable_error(400, "invalid_value", "value")


def store_credential(key: str, value: str) -> None:
    """Persist one validated credential. Callers must already have passed the authorization gate."""
    from backend.config import set_credential

    set_credential(key, value)
    _log.info("credential_set key=%s", key)  # key name only; never the value


def validate_service(service: object) -> str:
    """Return the normalized testable service name, or raise a stable 404 that does not echo input."""
    normalized = service.lower() if isinstance(service, str) else ""
    if normalized not in _TESTABLE_SERVICES:
        raise stable_error(404, "unknown_service", "service")
    return normalized


def provider_test_result(service: str) -> dict:
    """Report a service's mode without calling any provider helper.

    A service in dry-run mode reports ``dry_run``. A service in live mode reports ``blocked``:
    verifying live credentials would create a campaign or product at the provider, and no
    approved server-side policy permits that yet. Callers must already have passed the gate.
    """
    service = validate_service(service)
    try:
        from backend.config import is_dry_run

        live = not is_dry_run(service)
    except Exception as exc:
        _log.error("provider_test_failed service=%s error=%s", service, type(exc).__name__)
        return {"status": "error", "message": "Provider status unavailable"}
    if not live:
        return {"status": "dry_run", "message": f"{service} is in dry-run mode"}
    return {
        "status": "blocked",
        "message": "Live provider verification is disabled; no approved policy allows server-side provider calls",
    }


@router.post("/credentials/set")
async def set_credential(
    request: Request,
    response: Response,
    _access: WorkspaceAccess = Depends(credential_write_gate),
) -> dict:
    """Set one provider credential (verified internal operator only).

    Body: ``{"key": "<provider credential key>", "value": "<credential value>"}`` as
    ``application/json``, at most ``MAX_BODY_BYTES``. The key must be on the provider allowlist.

    Security notes:
      - Authorization comes only from the verified token and server-side membership role
      - The gate runs before the body is read; caller, workspace, and role fields are rejected
      - Credential value is NOT logged and NOT returned, including in validation errors
      - Failures return a stable code; exception text and paths are never reflected
    """
    response.headers["Cache-Control"] = "no-store"
    body = await read_bounded_json_object(request, frozenset({"key", "value"}))
    key = required_string(body, "key")
    value = required_string(body, "value")
    validate_credential_input(key, value)
    try:
        store_credential(key, value)
    except Exception as exc:
        _log.error("failed_to_set_credential key=%s error=%s", key, type(exc).__name__)
        raise stable_error(500, "credential_store_failed") from None
    return {"status": "ok", "message": f"Credential {key} saved successfully"}


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
        _log.error("failed_to_get_status error=%s", type(exc).__name__)
        raise stable_error(500, "status_unavailable") from None


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
        raise stable_error(404, "unknown_service", "service")

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


@router.post("/test/{service}")
async def test_credentials(
    service: str,
    response: Response,
    _access: WorkspaceAccess = Depends(credential_test_gate),
) -> dict:
    """Report whether a service is in dry-run or live mode (verified internal operator only).

    Never calls a provider: a live service reports ``blocked`` until an approved policy exists.
    The request body, if any, is never read.
    """
    response.headers["Cache-Control"] = "no-store"
    return provider_test_result(service)


__all__ = ["router"]
