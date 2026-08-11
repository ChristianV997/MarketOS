"""Combined provider, credential, subscription, and intelligence roadmap."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .credential_registry import CredentialRegistryReport, build_credential_registry
from .intelligence_provider_plan import IntelligenceProviderPlan, build_intelligence_provider_plan
from .provider_registry import ProviderRegistryReport, build_provider_registry
from .subscription_registry import SubscriptionRegistryReport, build_subscription_registry


def _clean(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {key: _clean(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set)):
        return [_clean(item) for item in value]
    return value


@dataclass(frozen=True)
class ProviderCredentialReport:
    report_version: str
    generated_at: str
    credentials: CredentialRegistryReport
    providers: ProviderRegistryReport
    subscriptions: SubscriptionRegistryReport
    intelligence_plan: IntelligenceProviderPlan
    provider_count: int
    credential_reference_count: int
    subscription_count: int
    intelligence_data_need_count: int
    estimated_monthly_cost_min: float
    estimated_monthly_cost_max: float
    highest_priority_providers: tuple[str, ...]
    providers_to_avoid_now: tuple[str, ...]
    credential_gaps: tuple[str, ...]
    subscription_consolidation: tuple[dict[str, Any], ...]
    activation_gates: tuple[dict[str, Any], ...]
    approval_links: tuple[dict[str, Any], ...]
    tool_links: tuple[dict[str, Any], ...]
    model_route_links: tuple[dict[str, Any], ...]
    safety_summary: dict[str, Any]
    next_best_action: str

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)

    def to_markdown(self) -> str:
        phase_cost = next((item for item in self.subscriptions.cost_estimates if item.phase == "phase_2_live_read_only_intelligence"), self.subscriptions.cost_estimates[0])
        lines = ["# CompanyOS Provider / Credential Registry", "", "## Executive Summary", "", f"- Providers: **{self.provider_count}**", f"- Credential references: **{self.credential_reference_count}**", f"- Subscription references: **{self.subscription_count}**", f"- Intelligence data needs: **{self.intelligence_data_need_count}**", f"- Planning cost band: **${phase_cost.monthly_min:.0f}-${phase_cost.monthly_max:.0f}/month** for Phase 2 candidates", "- Mode: **offline, metadata-only, fail-closed**", "", "## Highest-Priority Providers", ""]
        lines.extend(f"- **{item}**" for item in self.highest_priority_providers)
        lines += ["", "## Credential Gaps", ""]
        lines.extend(f"- {item}" for item in self.credential_gaps[:8])
        lines += ["", "## Intelligence Plan", "", "| Data need | Current mode | Recommended sequence |", "|---|---|---|"]
        lines.extend(f"| {item.data_need_id} | {item.current_mode} | {' -> '.join(item.recommended_provider_sequence)} |" for item in self.intelligence_plan.data_needs)
        lines += ["", "## Activation Gates", ""]
        lines.extend(f"- {item['provider_id']}: {item['gate_type']} - {item['status']}" for item in self.activation_gates)
        lines += ["", "## Providers To Avoid Now", ""]
        lines.extend(f"- {item}" for item in self.providers_to_avoid_now)
        lines += ["", "## Safety", "", "- Only safe references and planning bands are stored; No secret values are present.", "- No provider, model, vector, CRM, accounting, messaging, payment, ad, publishing, or subscription action occurred.", "", "## Next Best Action", "", self.next_best_action, ""]
        return "\n".join(lines)


def build_provider_credential_report(*, generated_at: str = "offline-deterministic", phase: str | None = None, provider: str | None = None, seeds: Mapping[str, Mapping[str, Any]] | None = None) -> ProviderCredentialReport:
    seeds = seeds or {}
    credentials = build_credential_registry(generated_at=generated_at, seed=seeds.get("credentials"))
    providers = build_provider_registry(generated_at=generated_at, seed=seeds.get("providers"))
    subscriptions = build_subscription_registry(generated_at=generated_at, phase=phase, seed=seeds.get("subscriptions"))
    intelligence = build_intelligence_provider_plan(generated_at=generated_at, seed=seeds.get("intelligence_plan"))
    if provider:
        provider = provider.lower().replace(" ", "-")
        if not any(item.provider_id == provider for item in providers.providers):
            raise ValueError(f"unknown provider: {provider}")
        priority = tuple(item.provider_id for item in providers.providers if item.provider_id == provider)
    else:
        priority = tuple(item for item in ("apify", "dataforseo", "serpapi", "litellm", "langfuse") if any(candidate.provider_id == item for candidate in providers.providers))
    phase_cost = next((item for item in subscriptions.cost_estimates if item.phase == (phase or "phase_2_live_read_only_intelligence")), subscriptions.cost_estimates[0])
    safety = {"read_only": True, "network_calls": False, "mutated": False, "secret_values_stored": False, "provider_calls": False, "model_calls": False, "vector_indexing": False, "subscriptions_activated": False, "fail_closed": True}
    return ProviderCredentialReport("companyos-provider-credential-report-v1", generated_at, credentials, providers, subscriptions, intelligence, len(providers.providers), len(credentials.credentials), len(subscriptions.plans), len(intelligence.data_needs), phase_cost.monthly_min, phase_cost.monthly_max, priority, providers.providers_to_avoid_now, credentials.credential_gaps, tuple(_clean(item) for item in subscriptions.consolidation_recommendations), tuple(_clean(item) for item in intelligence.activation_gates), tuple(_clean(item) for item in credentials.approval_links), tuple(_clean(item) for item in credentials.tool_links), tuple(_clean(item) for item in credentials.model_route_links), safety, "Keep all credentials as references only; prioritize an operator-approved Apify/DataForSEO metadata decision after the existing Approval Ledger gate.")


__all__ = ["ProviderCredentialReport", "build_provider_credential_report"]
