"""backend.workspaces.credential_scope — which integrations are configured.

Wraps backend.config.list_configured_services() rather than reinventing
credential tracking. Never exposes secret values, never raises.

backend.config has real credential keys for meta/tiktok/shopify/stripe/
supabase/ga4/woocommerce/mercadopago_mx/chatwoot/mautic/activepieces/
posthog_backend/hostinger (confirmed via backend/config.py::_SERVICE_CREDENTIALS).
Integrations that have no backing credential key yet (Twenty CRM — AGPL-3.0,
deferred pending legal review; WhatsApp, email, calendar, generic suppliers)
are reported honestly as "not_yet_supported" rather than faking a status.
"""
from __future__ import annotations

from typing import Any

from .client_workspace import ClientWorkspace

# integration name -> backend.config service key, or None if unsupported today
_INTEGRATION_TO_CONFIG_SERVICE: dict[str, str | None] = {
    "shopify": "shopify",
    "meta_ads": "meta",
    "tiktok_ads": "tiktok",
    "ga4": "ga4",
    "payment_provider": "stripe",
    "suppliers": None,
    "crm": None,
    "whatsapp": None,
    "email": None,
    "calendar": None,
    "content_scheduler": None,
    "woocommerce": "woocommerce",
    "payment_provider_mx_stripe": "stripe",
    "payment_provider_mx_mercadopago": "mercadopago_mx",
    "conversation_provider_chatwoot": "chatwoot",
    "marketing_automation_provider_mautic": "mautic",
    "customer_automation_provider_activepieces": "activepieces",
    "analytics_provider_posthog_backend": "posthog_backend",
    "hosting_provider_hostinger": "hostinger",
    # Twenty CRM remains unwired: AGPL-3.0, deferred pending legal review
    # (explicit prior user decision, left untouched — see
    # docs/oss/LICENSE_MANIFEST.yml and docs/COST_AWARE_INTEGRATION_AUDIT.md).
    "crm_provider_twenty": None,
}

_STATUS_CONFIGURED = "configured"
_STATUS_NOT_CONFIGURED = "not_configured"
_STATUS_NOT_YET_SUPPORTED = "not_yet_supported"


def scope_for(workspace: ClientWorkspace) -> dict[str, dict[str, Any]]:
    """Return {integration: {status, allowed, dry_run}} for every known
    integration. `allowed` additionally reflects workspace.allowed_integrations
    (empty allowed_integrations means "no restriction" — everything the
    credential layer supports is allowed, matching the common single-tenant
    internal-workspace case)."""
    try:
        from backend.config import is_dry_run, list_configured_services
        configured = list_configured_services()
    except Exception:
        configured, is_dry_run = {}, (lambda _svc: True)  # type: ignore[assignment]

    restrict = bool(workspace.allowed_integrations)
    out: dict[str, dict[str, Any]] = {}
    for integration, config_service in _INTEGRATION_TO_CONFIG_SERVICE.items():
        if config_service is None:
            status = _STATUS_NOT_YET_SUPPORTED
            dry_run = True
        else:
            is_configured = bool(configured.get(config_service, False))
            status = _STATUS_CONFIGURED if is_configured else _STATUS_NOT_CONFIGURED
            try:
                dry_run = is_dry_run(config_service)
            except Exception:
                dry_run = True
        allowed = (not restrict) or (integration in workspace.allowed_integrations)
        out[integration] = {"status": status, "allowed": allowed, "dry_run": dry_run}
    return out
