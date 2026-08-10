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
    }


__all__ = ["mvp_deployment_status"]
