"""backend.providers.registry — ProviderRegistry, the Provider Registry's
in-memory catalog store.

Precedent: backend.adapters.research.registry.ResearchAdapterRegistry (the
one existing register/get-by-name pattern in the repo) — this registry
holds static catalog data rather than live adapter instances, so it adds
`list`/`by_category` lookups that catalog/pricing comparison needs, and
raises on duplicate registration rather than silently overwriting (a
duplicate provider_id is always a bug, never an intentional override).
"""
from __future__ import annotations

from typing import Any

from .schemas import Provider, ProviderIntegrationStatus


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, Provider] = {}

    def register(self, provider: Provider) -> None:
        if provider.provider_id in self._providers:
            raise ValueError(f"duplicate provider_id: {provider.provider_id}")
        self._providers[provider.provider_id] = provider

    def get(self, provider_id: str) -> Provider:
        if provider_id not in self._providers:
            raise KeyError(f"unknown provider_id: {provider_id}")
        return self._providers[provider_id]

    def list(self) -> tuple[Provider, ...]:
        return tuple(self._providers.values())

    def by_category(self, category: str) -> tuple[Provider, ...]:
        return tuple(p for p in self._providers.values() if p.category == category)


provider_registry = ProviderRegistry()

# provider_id -> backend.workspaces.credential_scope integration key, or None
# if this provider has no tracked credential (catalog-only providers, or
# providers whose credentials predate credential_scope's tracked set, e.g.
# medusa/n8n/postiz already gate through their own adapter's env vars).
_PROVIDER_TO_INTEGRATION_KEY: dict[str, str] = {
    "woocommerce": "woocommerce",
    "stripe_mx": "payment_provider_mx_stripe",
    "mercado_pago_mx": "payment_provider_mx_mercadopago",
    "shopify": "shopify",
}


def integration_status_for(provider_id: str, workspace: Any = None) -> ProviderIntegrationStatus:
    """Never raises. Composes backend.workspaces.credential_scope.scope_for
    rather than re-deriving credential tracking. Providers with no entry in
    _PROVIDER_TO_INTEGRATION_KEY (e.g. catalog-only providers, or adapters
    that predate credential_scope's tracked integration set) honestly report
    "not_yet_supported", matching credential_scope.py's own convention."""
    provider = provider_registry.get(provider_id)
    integration_key = _PROVIDER_TO_INTEGRATION_KEY.get(provider_id)
    credential_status = "not_yet_supported"
    dry_run = True
    if integration_key is not None and workspace is not None:
        try:
            from backend.workspaces.credential_scope import scope_for
            scope = scope_for(workspace).get(integration_key, {})
            credential_status = scope.get("status", "not_yet_supported")
            dry_run = bool(scope.get("dry_run", True))
        except Exception:
            pass
    usable_now = provider.integration_status == "adapter_available" and credential_status == "configured"
    return ProviderIntegrationStatus(
        provider_id=provider_id,
        catalog_state=provider.integration_status,
        credential_status=credential_status,
        dry_run=dry_run,
        usable_now=usable_now,
    )
