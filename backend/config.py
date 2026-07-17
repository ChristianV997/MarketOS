"""backend.config — centralized credential and configuration management.

Credentials are stored in environment variables or a local encrypted config file.
Falls back to dry-run mock when credentials are absent.

Usage:
  from backend.config import get_credential, is_dry_run
  token = get_credential("META_ACCESS_TOKEN")
  if is_dry_run("meta"):
      print("Meta is in dry-run mode (no real spend)")
"""
import json
import logging
import os
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)

# Credential storage location (can be overridden via env)
_CONFIG_PATH = Path(os.getenv("MARKETOS_CONFIG_PATH", "~/.marketos/credentials.json")).expanduser()


def _ensure_config_dir() -> None:
    """Ensure config directory exists."""
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)


def _load_config() -> dict:
    """Load config from file if it exists."""
    _ensure_config_dir()
    if _CONFIG_PATH.exists():
        try:
            with open(_CONFIG_PATH) as f:
                return json.load(f)
        except Exception as exc:
            _log.warning("Failed to load config: %s", exc)
    return {}


def _save_config(cfg: dict) -> None:
    """Save config to file (non-destructive: merges with existing)."""
    _ensure_config_dir()
    try:
        existing = _load_config()
        existing.update(cfg)
        with open(_CONFIG_PATH, "w") as f:
            json.dump(existing, f, indent=2)
        # Restrict permissions so only owner can read
        _CONFIG_PATH.chmod(0o600)
    except Exception as exc:
        _log.error("Failed to save config: %s", exc)


def get_credential(key: str, default: Optional[str] = None) -> Optional[str]:
    """Retrieve a credential by key.

    Precedence:
      1. Environment variable (KEY)
      2. Config file (~/.marketos/credentials.json)
      3. Default value (if provided)
      4. None
    """
    # Try environment first
    env_val = os.getenv(key)
    if env_val:
        return env_val

    # Try config file
    cfg = _load_config()
    if key in cfg:
        return cfg[key]

    # Return default or None
    return default


def set_credential(key: str, value: str) -> None:
    """Store a credential persistently."""
    _save_config({key: value})
    _log.info("Credential stored: %s", key)


def is_dry_run(service: str) -> bool:
    """Check if a service is in dry-run mode.

    Returns True if:
      - <SERVICE>_DRY_RUN env var is set to 'true'
      - Or credentials are missing
    """
    dry_run_key = f"{service.upper()}_DRY_RUN"
    env_val = os.getenv(dry_run_key, "").lower()
    if env_val == "false":
        return False  # Explicitly enabled real mode
    if env_val == "true":
        return True   # Explicitly in dry-run

    # Default: dry-run if no credentials
    cred_keys = _SERVICE_CREDENTIALS.get(service.lower(), [])
    has_creds = all(get_credential(k) for k in cred_keys)
    return not has_creds


# ── service credential mappings ───────────────────────────────────────────────

_SERVICE_CREDENTIALS = {
    "meta": ["META_ACCESS_TOKEN", "META_AD_ACCOUNT_ID"],
    "tiktok": ["TIKTOK_ACCESS_TOKEN", "TIKTOK_ADVERTISER_ID"],
    "shopify": ["SHOPIFY_STORE_URL", "SHOPIFY_API_KEY", "SHOPIFY_API_PASSWORD"],
    "supabase": ["SUPABASE_URL", "SUPABASE_ANON_KEY"],
    "ga4": ["GA4_PROPERTY_ID", "GA4_API_KEY"],
}


def get_service_credentials(service: str) -> dict:
    """Retrieve all credentials for a service as a dict."""
    result = {}
    for key in _SERVICE_CREDENTIALS.get(service.lower(), []):
        val = get_credential(key)
        if val:
            result[key] = val
    return result


def list_configured_services() -> dict[str, bool]:
    """List all services and their configuration status.

    Returns:
      {service_name: is_ready}  where is_ready means credentials present + not dry-run
    """
    result = {}
    for service in _SERVICE_CREDENTIALS.keys():
        creds = get_service_credentials(service)
        is_ready = bool(creds) and not is_dry_run(service)
        result[service] = is_ready
    return result


def validate_credentials(service: str) -> tuple[bool, str]:
    """Validate that all required credentials for a service are present.

    Returns:
      (is_valid, message)
    """
    required = _SERVICE_CREDENTIALS.get(service.lower(), [])
    missing = [k for k in required if not get_credential(k)]

    if missing:
        return False, f"Missing credentials: {', '.join(missing)}"

    return True, "All credentials present"


__all__ = [
    "get_credential",
    "set_credential",
    "is_dry_run",
    "get_service_credentials",
    "list_configured_services",
    "validate_credentials",
]
