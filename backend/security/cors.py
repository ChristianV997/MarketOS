"""Safe, explicit CORS configuration for local, staging, and production deployments."""
from __future__ import annotations

import os
from typing import Mapping
from urllib.parse import urlparse

DEFAULT_LOCAL_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
]


def parse_allowed_origins(value: str | None) -> list[str]:
    """Normalize a comma-separated origin setting without accepting paths."""
    return list(dict.fromkeys(item.strip().rstrip("/") for item in (value or "").split(",") if item.strip()))


def is_production_cors_policy(environ: Mapping[str, str] | None = None) -> bool:
    """Check if runtime environment enforces strict production CORS rules."""
    env = os.environ if environ is None else environ
    env_name = env.get("MARKETOS_ENVIRONMENT", "").strip().lower()
    if env_name in {"production", "prod", "staging", "hosted"}:
        return True
    if env.get("RENDER", "").strip().lower() == "true":
        return True
    if env.get("RAILWAY_ENVIRONMENT", "").strip():
        return True
    if env.get("MARKETOS_HOSTED", "0").strip().lower() in {"1", "true", "yes", "on"}:
        return True
    if env.get("MARKETOS_MVP_MODE", "0").strip().lower() in {"1", "true", "yes", "on"}:
        return True
    return False


def validate_allowed_origins(origins: list[str], *, mvp_mode: bool) -> dict[str, object]:
    """Validate list of origin strings against security requirements."""
    warnings: list[str] = []
    blockers: list[str] = []
    normalized = parse_allowed_origins(",".join(origins))
    invalid: list[str] = []

    for origin in normalized:
        if origin == "*":
            warnings.append("wildcard_origin_allows_any_browser_origin")
            if mvp_mode:
                blockers.append("wildcard_origin_not_allowed_in_mvp_mode")
            continue
        parsed = urlparse(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path not in {"", "/"}:
            invalid.append(origin)

    if invalid:
        blockers.append("invalid_origin_format")

    if not normalized:
        warnings.append("allowed_origins_unconfigured")
        if mvp_mode:
            blockers.append("allowed_origins_required_in_mvp_mode")

    return {
        "configured": bool(normalized),
        "origins": normalized,
        "allowed_origin_count": len(normalized),
        "invalid_origins": invalid,
        "warnings": warnings,
        "blockers": blockers,
        "mvp_safe": not blockers,
        "credentials_enabled": False,
    }


def get_effective_allowed_origins(environ: Mapping[str, str] | None = None) -> list[str]:
    """Get the effective allowed origins depending on runtime environment."""
    env = os.environ if environ is None else environ
    raw = env.get("ALLOWED_ORIGINS")

    if raw is not None and raw.strip():
        return parse_allowed_origins(raw)

    # In local development without explicit ALLOWED_ORIGINS, use safe localhost defaults
    if not is_production_cors_policy(env):
        return list(DEFAULT_LOCAL_ORIGINS)

    # In production/hosted mode, do not invent origins; return empty which will fail validation
    return []


def validate_cors_for_startup(environ: Mapping[str, str] | None = None) -> list[str]:
    """Fail closed at application startup if production CORS configuration is ambiguous or insecure."""
    env = os.environ if environ is None else environ
    prod = is_production_cors_policy(env)
    effective = get_effective_allowed_origins(env)
    report = validate_allowed_origins(effective, mvp_mode=prod)

    if prod and not report["mvp_safe"]:
        blockers = report["blockers"]
        raise RuntimeError(
            f"Production CORS configuration rejected: {', '.join(str(b) for b in blockers)}. "
            "Explicit ALLOWED_ORIGINS (e.g. 'https://app.marketos.com') is required in production."
        )

    return effective


def explain_cors_readiness(environ: Mapping[str, str] | None = None) -> dict[str, object]:
    """Diagnostic report for CORS readiness and safety."""
    values = os.environ if environ is None else environ
    mvp_mode = values.get("MARKETOS_MVP_MODE", "0").strip().lower() in {"1", "true", "yes", "on"}
    public_gate = values.get("MARKETOS_PUBLIC_COMMERCE_RUNS", "0") == "1"
    prod = is_production_cors_policy(values)
    raw_origins = parse_allowed_origins(values.get("ALLOWED_ORIGINS"))
    report = validate_allowed_origins(raw_origins, mvp_mode=mvp_mode or public_gate)
    report.update({
        "mvp_mode": mvp_mode,
        "production_mode": prod,
        "public_commerce_runs_enabled": public_gate,
        "effective_origins": get_effective_allowed_origins(values),
    })
    return report


__all__ = [
    "DEFAULT_LOCAL_ORIGINS",
    "explain_cors_readiness",
    "get_effective_allowed_origins",
    "is_production_cors_policy",
    "parse_allowed_origins",
    "validate_allowed_origins",
    "validate_cors_for_startup",
]
