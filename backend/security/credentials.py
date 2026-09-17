"""Credential safety, validation, and diagnostics utilities."""
from __future__ import annotations

import os
import re
from typing import Any, Mapping

_TOKEN_SHAPED = re.compile(r"(?:bearer\s+)?[A-Za-z0-9_\-]{20,}", re.I)
_ALLOWED_KEY_RE = re.compile(r"^[A-Z0-9_]{3,64}$")

# Recognized service credential keys that MarketOS knows how to manage safely
ALLOWED_CREDENTIAL_KEYS = frozenset({
    "META_ACCESS_TOKEN",
    "META_AD_ACCOUNT_ID",
    "TIKTOK_ACCESS_TOKEN",
    "TIKTOK_ADVERTISER_ID",
    "SHOPIFY_STORE_URL",
    "SHOPIFY_ACCESS_TOKEN",
    "SHOPIFY_WEBHOOK_SECRET",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "GA4_PROPERTY_ID",
    "GA4_API_KEY",
    "WOOCOMMERCE_STORE_URL",
    "WOOCOMMERCE_CONSUMER_KEY",
    "WOOCOMMERCE_CONSUMER_SECRET",
    "MERCADOPAGO_ACCESS_TOKEN",
    "CHATWOOT_BASE_URL",
    "CHATWOOT_API_ACCESS_TOKEN",
    "CHATWOOT_ACCOUNT_ID",
    "MAUTIC_BASE_URL",
    "MAUTIC_USERNAME",
    "MAUTIC_PASSWORD",
    "ACTIVEPIECES_BASE_URL",
    "ACTIVEPIECES_API_KEY",
    "POSTHOG_PROJECT_API_KEY",
    "HOSTINGER_API_TOKEN",
    "CJ_EMAIL",
    "CJ_API_KEY",
    "MARKETOS_OPERATOR_TOKEN",
})


def mask_secret(value: str | None) -> str:
    """Safely mask a secret value for status reporting, never showing the full secret."""
    if not value:
        return ""
    val = str(value).strip()
    if len(val) <= 8:
        return "********"
    # Show at most first 4 and last 4 characters
    return f"{val[:4]}...{val[-4:]}"


def is_valid_credential_key(key: str) -> bool:
    """Validate that credential key matches format and allowed keys."""
    if not key or not isinstance(key, str):
        return False
    clean = key.strip()
    if not _ALLOWED_KEY_RE.match(clean):
        return False
    return clean in ALLOWED_CREDENTIAL_KEYS


def is_token_shaped(value: str | None) -> bool:
    """Detect if a string looks like a sensitive bearer token or API key."""
    if not value:
        return False
    return bool(_TOKEN_SHAPED.search(str(value)))


def diagnose_credential_safety(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Diagnose credential safety without ever leaking values or raw secrets."""
    env = os.environ if environ is None else environ
    from backend.security.auth import is_production_mode

    prod = is_production_mode(env)
    configured_keys: list[str] = []
    masked_diagnostics: dict[str, Any] = {}

    for key in sorted(ALLOWED_CREDENTIAL_KEYS):
        val = env.get(key)
        if val and val.strip():
            configured_keys.append(key)
            masked_diagnostics[key] = {
                "present": True,
                "length": len(val.strip()),
                "preview": mask_secret(val.strip()),
            }
        else:
            masked_diagnostics[key] = {
                "present": False,
            }

    storage_mode = "environment_variables"
    if env.get("MARKETOS_CONFIG_PATH"):
        storage_mode = "custom_config_file"
    elif prod:
        storage_mode = "platform_secret_store"

    return {
        "production_mode": prod,
        "storage_mode": storage_mode,
        "total_managed_keys": len(ALLOWED_CREDENTIAL_KEYS),
        "configured_key_count": len(configured_keys),
        "configured_keys": configured_keys,
        "masked_status": masked_diagnostics,
        "raw_values_exposed": False,
    }


__all__ = [
    "ALLOWED_CREDENTIAL_KEYS",
    "diagnose_credential_safety",
    "is_token_shaped",
    "is_valid_credential_key",
    "mask_secret",
]
