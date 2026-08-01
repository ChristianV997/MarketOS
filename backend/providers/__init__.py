"""backend.providers — the Provider Registry.

Importing this package (or provider_catalog directly) registers every
catalog provider into the module-level `provider_registry` singleton.
"""
from __future__ import annotations

from . import provider_catalog  # noqa: F401 — import for registration side effect
from .registry import ProviderRegistry, integration_status_for, provider_registry
from .schemas import (
    Provider,
    ProviderCostComponent,
    ProviderIntegrationStatus,
    ProviderPlan,
    ProviderRecommendation,
    ProviderRisk,
)

__all__ = [
    "ProviderRegistry",
    "provider_registry",
    "integration_status_for",
    "Provider",
    "ProviderCostComponent",
    "ProviderPlan",
    "ProviderRisk",
    "ProviderIntegrationStatus",
    "ProviderRecommendation",
]
