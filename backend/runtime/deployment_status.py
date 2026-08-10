"""Safe, non-secret deployment status fields for the Phase 1 MVP."""
from __future__ import annotations

import os


def mvp_deployment_status() -> dict[str, object]:
    """Return deployment booleans without exposing configuration values."""
    try:
        from backend.runtime.mvp_mode import load_mvp_profile, mvp_readiness_report

        profile = load_mvp_profile()
        runtime = mvp_readiness_report(profile=profile)
        live_flags_disabled = not runtime["unsafe_live_flags"]
        profile_loaded = True
    except Exception:
        live_flags_disabled = False
        profile_loaded = False

    try:
        from backend.security.cors import explain_cors_readiness
        from backend.security.rate_limit import explain_rate_limit_status
        from backend.observability.phase1_telemetry import telemetry_readiness
        cors = explain_cors_readiness()
        limits = explain_rate_limit_status()
        telemetry = telemetry_readiness()
    except Exception:
        cors = {"configured": False, "mvp_safe": False, "allowed_origin_count": 0, "warnings": ["security_helpers_unavailable"]}
        limits = {"enabled": False}
        telemetry = {"sentry_configured": False, "sentry_enabled": False, "safe_mode": True, "sentry_pii_disabled": True, "telemetry_fail_open": True, "telemetry_secret_redaction": True}
    return {
        "mvp_profile_loaded": profile_loaded,
        "event_read_jsonl_path_configured": bool(os.getenv("MARKETOS_EVENT_READ_JSONL_PATH")),
        "event_write_jsonl_path_configured": bool(os.getenv("MARKETOS_EVENT_WRITE_JSONL_PATH")),
        "public_commerce_runs_enabled": os.getenv("MARKETOS_PUBLIC_COMMERCE_RUNS", "0") == "1",
        "supabase_staging_configured": bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_ROLE_KEY")),
        "supabase_write_gate_enabled": os.getenv("MARKETOS_SUPABASE_CANONICAL_EVENTS", "0") == "1",
        "operator_dashboard_expected_route": "/operator/events",
        "live_mutation_flags_disabled": live_flags_disabled,
        "no_credentials_required_for_mvp_smoke": True,
        "cors_configured": bool(cors.get("configured")),
        "cors_mvp_safe": bool(cors.get("mvp_safe")),
        "allowed_origin_count": int(cors.get("allowed_origin_count", 0)),
        "request_id_middleware_enabled": True,
        "rate_limit_enabled": bool(limits.get("enabled")),
        "public_run_rate_limit": limits.get("public_run_rate_limit"),
        "event_read_rate_limit": limits.get("event_read_rate_limit"),
        "safe_logging_enabled": True,
        "secret_redaction_enabled": True,
        "sentry_configured": bool(telemetry.get("sentry_configured")),
        "sentry_enabled": bool(telemetry.get("sentry_enabled")),
        "sentry_safe_mode": bool(telemetry.get("sentry_safe_mode", True)),
        "sentry_pii_disabled": bool(telemetry.get("sentry_pii_disabled", True)),
        "posthog_frontend_configured": bool(telemetry.get("posthog_frontend_configured")),
        "posthog_explicit_events_only": True,
        "telemetry_fail_open": True,
        "telemetry_secret_redaction": True,
    }


__all__ = ["mvp_deployment_status"]
