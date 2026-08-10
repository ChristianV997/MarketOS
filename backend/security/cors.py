"""Safe, explicit CORS configuration for the operator-facing MVP API."""
from __future__ import annotations

import os
from urllib.parse import urlparse


def parse_allowed_origins(value: str | None) -> list[str]:
    """Normalize a comma-separated origin setting without accepting paths."""
    return list(dict.fromkeys(item.strip().rstrip("/") for item in (value or "").split(",") if item.strip()))


def validate_allowed_origins(origins: list[str], *, mvp_mode: bool) -> dict[str, object]:
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


def explain_cors_readiness(environ: dict[str, str] | None = None) -> dict[str, object]:
    values = os.environ if environ is None else environ
    mvp_mode = values.get("MARKETOS_MVP_MODE", "0").strip().lower() in {"1", "true", "yes", "on"}
    public_gate = values.get("MARKETOS_PUBLIC_COMMERCE_RUNS", "0") == "1"
    report = validate_allowed_origins(parse_allowed_origins(values.get("ALLOWED_ORIGINS")), mvp_mode=mvp_mode or public_gate)
    report.update({"mvp_mode": mvp_mode, "public_commerce_runs_enabled": public_gate})
    return report


__all__ = ["explain_cors_readiness", "parse_allowed_origins", "validate_allowed_origins"]
