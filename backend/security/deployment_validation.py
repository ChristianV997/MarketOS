"""Deployment hardening preflight and runtime environment validation."""
from __future__ import annotations

import os
from typing import Any, Mapping

from backend.security.auth import is_production_mode
from backend.security.cors import get_effective_allowed_origins, validate_allowed_origins


def validate_production_deployment(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Validate that the deployment configuration meets production security standards."""
    env = os.environ if environ is None else environ
    prod = is_production_mode(env)

    blockers: list[str] = []
    warnings: list[str] = []

    # 1. Check Authentication Configuration
    op_token: str | None = env.get("MARKETOS_OPERATOR_TOKEN") or env.get("MARKETOS_API_KEY")
    client_tokens = env.get("MARKETOS_CLIENT_TOKENS") or env.get("MARKETOS_CLIENT_TOKEN")
    auth_disabled = env.get("MARKETOS_AUTH_DISABLED", "false").strip().lower() in {"1", "true", "yes", "on"}

    if prod:
        if auth_disabled:
            blockers.append("auth_disabled_forbidden_in_production")
        if not op_token and not client_tokens:
            blockers.append("operator_token_required_in_production")
    else:
        if not op_token and not auth_disabled:
            warnings.append("local_auth_unconfigured_set_MARKETOS_OPERATOR_TOKEN_or_MARKETOS_AUTH_DISABLED")

    # 2. Check CORS Configuration
    effective_origins = get_effective_allowed_origins(env)
    cors_report = validate_allowed_origins(effective_origins, mvp_mode=prod)
    if prod and not cors_report["mvp_safe"]:
        for b in cors_report["blockers"]:
            blockers.append(f"cors_{b}")
    for w in cors_report["warnings"]:
        warnings.append(f"cors_{w}")

    # 3. Check Live Actions & Spend Protection
    live_enabled = env.get("MARKETOS_ENABLE_LIVE_ACTIONS", "false").strip().lower() in {"1", "true", "yes", "on"}
    if live_enabled and not op_token:
        blockers.append("live_actions_enabled_without_operator_token")

    # 4. Check Webhook Secrets Configuration
    stripe_configured = bool(env.get("STRIPE_WEBHOOK_SECRET"))
    shopify_configured = bool(env.get("SHOPIFY_WEBHOOK_SECRET"))
    cj_configured = bool(env.get("CJ_WEBHOOK_SECRET"))

    ready = len(blockers) == 0

    return {
        "status": "ready" if ready else "blocked",
        "ready": ready,
        "production_mode": prod,
        "blockers": blockers,
        "warnings": warnings,
        "checks": {
            "authentication": {
                "configured": bool(op_token or client_tokens),
                "operator_configured": bool(op_token),
                "auth_disabled": auth_disabled,
                "status": "pass" if (op_token or client_tokens or not prod) else "fail",
            },
            "cors": {
                "origins": effective_origins,
                "wildcard_allowed": "*" in effective_origins,
                "status": "pass" if cors_report["mvp_safe"] else "fail",
            },
            "webhooks": {
                "stripe_secret_configured": stripe_configured,
                "shopify_secret_configured": shopify_configured,
                "cj_secret_configured": cj_configured,
            },
            "live_safety": {
                "live_actions_enabled": live_enabled,
                "dry_run_default": True,
            },
        },
    }


__all__ = ["validate_production_deployment"]
