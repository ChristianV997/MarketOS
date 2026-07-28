"""backend.observability.sentry_init — real Sentry SDK initialization.

``sentry-sdk[fastapi]`` has been a declared dependency since early in this
project but was never actually initialized anywhere — this is the cheapest
observability win available per the Tier 3 consolidation plan: a few lines
of ``sentry_sdk.init()`` gets full exception stack traces for free, layered
*under* (not replacing) the existing hand-rolled Slack/Telegram business-logic
alerts (backend.monitoring.alerts) — those stay domain-specific (drawdown
breach, kill-switch fired, ...) and won't come from a generic APM tool.

No-op (never raises, never even imports sentry_sdk) unless SENTRY_DSN is
set — same "presence of the credential is the opt-in" convention as every
other integration in this codebase.
"""
from __future__ import annotations

import logging
import os

_log = logging.getLogger(__name__)

_initialized = False


def init_sentry(component: str = "marketos") -> bool:
    """Initialize the Sentry SDK for the calling process if SENTRY_DSN is
    set. Idempotent — safe to call multiple times (e.g. once per worker
    process). Returns True if Sentry is now active, False otherwise
    (unconfigured or the SDK failed to import/initialize).
    """
    global _initialized
    if _initialized:
        return True

    dsn = os.getenv("SENTRY_DSN", "")
    if not dsn:
        return False

    try:
        import sentry_sdk

        integrations = []
        try:
            from sentry_sdk.integrations.fastapi import FastApiIntegration
            integrations.append(FastApiIntegration())
        except ImportError:
            pass

        sentry_sdk.init(
            dsn=dsn,
            environment=os.getenv("SENTRY_ENVIRONMENT", "development"),
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.0")),
            integrations=integrations,
        )
        sentry_sdk.set_tag("component", component)
        _initialized = True
        _log.info("sentry_initialized component=%s", component)
        return True
    except Exception as exc:
        _log.warning("sentry_init_failed error=%s", exc)
        return False


def is_active() -> bool:
    return _initialized
