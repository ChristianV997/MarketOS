"""Default-off runtime guard for the small, advisory MarketOS MVP Island.

This module is intentionally a profile reader and policy guard, not an
orchestrator or feature flag system.  It does not enable integrations, make
network calls, or alter an existing execution path.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = ROOT / "deploy" / "mvp" / "marketos.mvp.json"
_TRUE = {"1", "true", "yes", "on"}


class MVPModeError(PermissionError):
    """Raised when an action is outside the explicit MVP Island."""


def load_mvp_profile(path: str | Path | None = None) -> dict[str, Any]:
    """Load and minimally validate the committed, machine-readable profile."""
    profile_path = Path(path) if path else PROFILE_PATH
    try:
        data = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MVPModeError(f"MVP profile is unavailable: {profile_path}") from exc
    required = {"enabled_modules", "disabled_modules", "forbidden_actions", "live_commerce_flags"}
    missing = sorted(key for key in required if not isinstance(data.get(key), list))
    if missing:
        raise MVPModeError(f"MVP profile missing list fields: {', '.join(missing)}")
    return data


def is_mvp_mode_enabled(environ: dict[str, str] | None = None) -> bool:
    values = os.environ if environ is None else environ
    return str(values.get("MARKETOS_MVP_MODE", "0")).strip().lower() in _TRUE


def enabled_modules(profile: dict[str, Any] | None = None) -> tuple[str, ...]:
    current = load_mvp_profile() if profile is None else profile
    return tuple(current["enabled_modules"])


def disabled_modules(profile: dict[str, Any] | None = None) -> tuple[str, ...]:
    current = load_mvp_profile() if profile is None else profile
    return tuple(current["disabled_modules"])


def assert_action_allowed(action_name: str, profile: dict[str, Any] | None = None) -> None:
    """Fail closed unless the requested action is one of the profile capabilities."""
    current = load_mvp_profile() if profile is None else profile
    allowed = set(current["enabled_modules"]) | set(current.get("manual_only_actions", []))
    if action_name not in allowed:
        raise MVPModeError(
            f"MVP Island blocks {action_name!r}; move it through explicit human approval outside the MVP profile."
        )


def mvp_readiness_report(environ: dict[str, str] | None = None, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return local configuration state without probing any provider."""
    values = os.environ if environ is None else environ
    current = load_mvp_profile() if profile is None else profile
    required = list(current.get("required_env_vars", []))
    optional = list(current.get("optional_env_vars", []))
    missing_required = [name for name in required if not values.get(name)]
    configured_optional = [name for name in optional if values.get(name)]
    unsafe_flags = []
    for name in current["live_commerce_flags"]:
        value = str(values.get(name, "")).strip().lower()
        if name.endswith("_DRY_RUN"):
            if value in {"false", "0", "no", "off"}:
                unsafe_flags.append(name)
        elif value in _TRUE:
            unsafe_flags.append(name)
    return {
        "profile": current.get("name"),
        "mvp_mode_enabled": is_mvp_mode_enabled(values),
        "enabled_modules": list(current["enabled_modules"]),
        "disabled_modules": list(current["disabled_modules"]),
        "missing_required_env": missing_required,
        "configured_optional_env": configured_optional,
        "unsafe_live_flags": unsafe_flags,
        "supabase_configured": bool(values.get("SUPABASE_URL") and values.get("SUPABASE_SERVICE_ROLE_KEY")),
        "public_network_enabled": str(values.get("MARKETOS_PUBLIC_SIGNAL_NETWORK", "0")).strip().lower() in _TRUE,
        "status": "blocked" if unsafe_flags else ("ready" if not missing_required else "partial"),
        "safety_note": "This report performs no provider health check and enables no service.",
    }


__all__ = ["MVPModeError", "assert_action_allowed", "disabled_modules", "enabled_modules", "is_mvp_mode_enabled", "load_mvp_profile", "mvp_readiness_report"]
