"""Optional, fail-open Sentry configuration for the Phase 1 MVP."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from backend.observability.telemetry_sanitization import safe_path_tag, safe_workspace_tag


@dataclass(frozen=True)
class TelemetryConfig:
    sentry_dsn_present: bool
    sentry_enabled: bool
    sentry_environment: str
    sentry_release: str | None
    sentry_traces_sample_rate: float
    posthog_server_enabled: bool
    safe_mode: bool
    pii_allowed: bool = False


def _sample_rate(value: str) -> float:
    try:
        return min(max(float(value), 0.0), 1.0)
    except ValueError:
        return 0.0


def telemetry_config_from_env(environ: dict[str, str] | None = None) -> TelemetryConfig:
    values = os.environ if environ is None else environ
    dsn = bool(values.get("SENTRY_DSN"))
    return TelemetryConfig(
        sentry_dsn_present=dsn,
        sentry_enabled=dsn,
        sentry_environment=values.get("SENTRY_ENVIRONMENT", "development"),
        sentry_release=values.get("SENTRY_RELEASE") or None,
        sentry_traces_sample_rate=_sample_rate(values.get("SENTRY_TRACES_SAMPLE_RATE", "0.0")),
        posthog_server_enabled=False,
        safe_mode=True,
    )


def telemetry_readiness(environ: dict[str, str] | None = None) -> dict[str, Any]:
    config = telemetry_config_from_env(environ)
    values = os.environ if environ is None else environ
    return {
        "sentry_configured": config.sentry_dsn_present,
        "sentry_enabled": config.sentry_enabled,
        "sentry_environment": config.sentry_environment,
        "sentry_release_present": bool(config.sentry_release),
        "sentry_traces_sample_rate": config.sentry_traces_sample_rate,
        "posthog_frontend_configured": bool(values.get("VITE_POSTHOG_KEY")),
        "posthog_server_enabled": False,
        "posthog_explicit_events_only": True,
        "safe_mode": config.safe_mode,
        "sentry_safe_mode": config.safe_mode,
        "sentry_pii_disabled": config.pii_allowed is False,
        "telemetry_fail_open": True,
        "telemetry_secret_redaction": True,
        "network_calls": False,
        "mutated": False,
    }


def initialize_phase1_telemetry(component: str = "marketos") -> bool:
    """Initialize the existing Sentry adapter; never fail application startup."""
    try:
        from backend.observability.sentry_init import init_sentry
        return init_sentry(component=component)
    except Exception:
        return False


def telemetry_enabled() -> bool:
    try:
        from backend.observability.sentry_init import is_active
        return is_active()
    except Exception:
        return False


def explain_telemetry_state(environ: dict[str, str] | None = None) -> dict[str, Any]:
    return telemetry_readiness(environ)


def set_request_sentry_context(*, request_id: str, method: str, path: str, mvp_mode: bool, read_only: bool, workspace_id: str | None = None, event_target: str | None = None) -> None:
    if not telemetry_enabled():
        return
    try:
        import sentry_sdk

        with sentry_sdk.configure_scope() as scope:
            scope.set_tag("request_id", request_id)
            scope.set_tag("http_method", method)
            scope.set_tag("path", safe_path_tag(path))
            scope.set_tag("mvp_mode", mvp_mode)
            scope.set_tag("read_only", read_only)
            if workspace_id:
                scope.set_tag("workspace_id", safe_workspace_tag(workspace_id))
            if event_target:
                scope.set_tag("event_target", safe_workspace_tag(event_target))
    except Exception:
        pass


__all__ = ["TelemetryConfig", "explain_telemetry_state", "initialize_phase1_telemetry", "set_request_sentry_context", "telemetry_config_from_env", "telemetry_enabled", "telemetry_readiness"]
