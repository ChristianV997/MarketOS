"""Offline roadmap for future marketplace and consumer-intelligence acquisition."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

ACQUISITION_MODES = ("fixture_only", "manual_import", "approved_live_read_only", "scheduled_read_only", "official_api_read_only", "blocked")


def _clean(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {key: _clean(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set)):
        return [_clean(item) for item in value]
    return value


@dataclass(frozen=True)
class DataAcquisitionMode:
    mode: str
    allowed: bool
    approval_required: bool
    network_allowed: bool
    notes: str

    def __post_init__(self) -> None:
        if self.mode not in ACQUISITION_MODES:
            raise ValueError(f"invalid acquisition mode: {self.mode}")


@dataclass(frozen=True)
class IntelligenceDataNeed:
    data_need_id: str
    description: str
    current_mode: str
    recommended_provider_sequence: tuple[str, ...]
    provider_candidates: tuple[str, ...]
    required_credentials: tuple[str, ...]
    approval_required: bool
    monthly_budget_cap: float
    tos_policy_review_required: bool
    privacy_review_required: bool
    output_evidence_model: str
    blocked_until: str


@dataclass(frozen=True)
class ProviderCoverageMapping:
    provider_id: str
    data_need_ids: tuple[str, ...]
    coverage_level: str
    acquisition_mode: str
    evidence_model: str
    gaps: tuple[str, ...]


@dataclass(frozen=True)
class ProviderCostBenefit:
    provider_id: str
    capability_gain: str
    estimated_monthly_cost_min: float
    estimated_monthly_cost_max: float
    time_saved: str
    value_risk: str
    recommendation: str


@dataclass(frozen=True)
class ProviderRiskReview:
    provider_id: str
    security_risk: str
    terms_risk: str
    privacy_risk: str
    operational_risk: str
    required_reviews: tuple[str, ...]
    default_action: str


@dataclass(frozen=True)
class ProviderActivationGate:
    gate_id: str
    provider_id: str
    gate_type: str
    required_evidence: tuple[str, ...]
    approval_type: str
    status: str
    blocking: bool


@dataclass(frozen=True)
class IntelligenceProviderPlan:
    report_version: str
    generated_at: str
    data_needs: tuple[IntelligenceDataNeed, ...]
    coverage: tuple[ProviderCoverageMapping, ...]
    acquisition_modes: tuple[DataAcquisitionMode, ...]
    cost_benefits: tuple[ProviderCostBenefit, ...]
    risk_reviews: tuple[ProviderRiskReview, ...]
    activation_gates: tuple[ProviderActivationGate, ...]
    safety_summary: dict[str, Any]
    next_best_action: str

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)

    def to_markdown(self) -> str:
        lines = ["# Intelligence Provider Plan", "", "## Data Needs", "", "| Need | Current mode | Recommended sequence | Budget cap |", "|---|---|---|---:|"]
        lines.extend(f"| {item.data_need_id} | {item.current_mode} | {' -> '.join(item.recommended_provider_sequence)} | ${item.monthly_budget_cap:.0f} |" for item in self.data_needs)
        lines += ["", "## Provider Coverage", "", "| Provider | Need coverage | Mode | Level |", "|---|---|---|---|"]
        lines.extend(f"| {item.provider_id} | {', '.join(item.data_need_ids)} | {item.acquisition_mode} | {item.coverage_level} |" for item in self.coverage)
        lines += ["", "## Activation Gates", ""]
        lines.extend(f"- {item.provider_id}: **{item.gate_type}** - {item.status}; evidence: {', '.join(item.required_evidence)}" for item in self.activation_gates)
        lines += ["", "## Safety", "", "- Fixture and manual import modes are implemented; approved live, scheduled, and official API modes are roadmap-only.", "- No actor run, scrape, search request, provider call, or credential validation occurred.", "", "## Next Best Action", "", self.next_best_action, ""]
        return "\n".join(lines)


def _need(need_id: str, description: str, sequence: tuple[str, ...], candidates: tuple[str, ...], evidence: str, budget: float = 0.0, credentials: tuple[str, ...] = ()) -> IntelligenceDataNeed:
    return IntelligenceDataNeed(need_id, description, "manual_import" if need_id in {"marketplace_demand", "supplier_feasibility", "consumer_attention", "review_extraction"} else "fixture_only", sequence, candidates, credentials, True, budget, True, True, evidence, "Approval Ledger + provider credential reference + terms/privacy review")


def build_intelligence_provider_plan(*, generated_at: str = "offline-deterministic", seed: Mapping[str, Any] | None = None) -> IntelligenceProviderPlan:
    needs = (
        _need("marketplace_demand", "Marketplace demand, rank, review, and price signals.", ("manual_import", "official-marketplace-apis", "apify"), ("official-marketplace-apis", "apify"), "MarketplaceTrendReport", 200, ("api_key", "oauth_token")),
        _need("competitor_pricing", "Public competitor offers, price coverage, and availability.", ("manual_import", "apify", "official-marketplace-apis"), ("apify", "official-marketplace-apis"), "CompetitionEvidence", 200, ("api_key",)),
        _need("supplier_feasibility", "Supplier cost, shipping, inventory, and delivery evidence.", ("manual_import", "official-marketplace-apis"), ("official-marketplace-apis",), "SupplierFeasibilityReport", 100, ("api_key",)),
        _need("review_extraction", "Review language, pain points, objections, and sentiment.", ("manual_import", "apify", "official-marketplace-apis"), ("apify", "official-marketplace-apis"), "ConsumerAttentionReport", 200, ("api_key",)),
        _need("consumer_attention", "Search, comments, creative, and public attention signals.", ("manual_import", "official-social-search-apis", "apify"), ("official-social-search-apis", "apify"), "ConsumerAttentionReport", 300, ("api_key", "oauth_token")),
        _need("search_serp_keyword", "Search/SERP, keyword, and demand proxy signals.", ("manual_import", "dataforseo", "serpapi"), ("dataforseo", "serpapi"), "MarketplaceTrendReport", 500, ("api_key",)),
        _need("ad_creative_signals", "Ad and creative signal snapshots for consulting reports.", ("manual_import", "apify", "official-social-search-apis"), ("apify", "official-social-search-apis"), "ConsumerAttentionReport", 300, ("api_key", "oauth_token")),
        _need("social_public_snapshots", "Public social and content snapshots without posting.", ("manual_import", "official-social-search-apis", "apify"), ("official-social-search-apis", "apify"), "ConsumerAttentionReport", 250, ("api_key", "oauth_token")),
        _need("official_api_validation", "Compliant official API validation after manual benchmark.", ("manual_import", "official-marketplace-apis", "official-social-search-apis"), ("official-marketplace-apis", "official-social-search-apis"), "CanonicalEvidence", 400, ("api_key", "oauth_token")),
        _need("scheduled_monitoring", "Bounded scheduled read-only evidence refresh.", ("manual_import", "apify"), ("apify",), "EvidenceRefreshReport", 200, ("api_key",)),
    )
    coverage = (
        ProviderCoverageMapping("apify", ("marketplace_demand", "competitor_pricing", "review_extraction", "consumer_attention", "ad_creative_signals", "social_public_snapshots", "scheduled_monitoring"), "broad_public", "approved_live_read_only", "sanitized evidence reports", ("robots/TOS and privacy review",)),
        ProviderCoverageMapping("dataforseo", ("search_serp_keyword",), "search_specialist", "approved_live_read_only", "MarketplaceTrendReport", ("cost and terms review",)),
        ProviderCoverageMapping("serpapi", ("search_serp_keyword",), "search_specialist", "approved_live_read_only", "MarketplaceTrendReport", ("overlap with DataForSEO",)),
        ProviderCoverageMapping("official-marketplace-apis", ("marketplace_demand", "competitor_pricing", "supplier_feasibility", "review_extraction", "official_api_validation"), "compliance_first", "official_api_read_only", "canonical evidence", ("provider-specific scopes",)),
        ProviderCoverageMapping("official-social-search-apis", ("consumer_attention", "social_public_snapshots", "official_api_validation"), "compliance_first", "official_api_read_only", "ConsumerAttentionReport", ("platform availability and policy",)),
        ProviderCoverageMapping("bright-data", ("competitor_pricing", "social_public_snapshots"), "enterprise_later", "blocked", "sanitized evidence", ("cost, terms, privacy, anti-bot risk")),
        ProviderCoverageMapping("oxylabs", ("competitor_pricing",), "enterprise_later", "blocked", "sanitized evidence", ("enterprise cost and policy risk")),
    )
    modes = tuple(DataAcquisitionMode(mode, mode in {"fixture_only", "manual_import"}, mode in {"approved_live_read_only", "scheduled_read_only", "official_api_read_only"}, False, "No network is permitted in the current CLI.") for mode in ACQUISITION_MODES)
    costs = tuple(ProviderCostBenefit(provider, "Adds bounded roadmap coverage", 0, 500 if provider in {"dataforseo", "bright-data", "oxylabs"} else 300, "Removes repeated manual work only after approval", "Unknown until a measured benchmark", "review_then_configure_reference" if provider in {"apify", "dataforseo", "serpapi"} else "delay") for provider in ("apify", "dataforseo", "serpapi", "official-marketplace-apis", "official-social-search-apis", "bright-data", "oxylabs"))
    risks = tuple(ProviderRiskReview(provider, "credential scope and secret-manager review", "terms/robots review", "privacy and retention review", "bounded quotas and failure handling", ("Approval Ledger", "provider credential reference", "sanitized output test"), "reference_only") for provider in ("apify", "dataforseo", "serpapi", "official-marketplace-apis", "official-social-search-apis", "bright-data", "oxylabs"))
    gates = tuple(ProviderActivationGate(f"activate-{provider}", provider, "provider_activation", ("owner", "secret-manager reference", "budget cap", "terms/privacy review", "read-only output test"), "provider_call", "blocked", True) for provider in ("apify", "dataforseo", "serpapi", "official-marketplace-apis", "official-social-search-apis", "bright-data", "oxylabs"))
    return IntelligenceProviderPlan("companyos-intelligence-provider-plan-v1", generated_at, needs, coverage, modes, costs, risks, gates, {"read_only": True, "network_calls": False, "mutated": False, "actor_runs": False, "scraping_performed": False, "credentials_present": False, "fail_closed": True}, "Use the existing fixture/manual intelligence layers; prepare Apify and DataForSEO reference metadata only after Approval Ledger review.")


__all__ = ["ACQUISITION_MODES", "DataAcquisitionMode", "IntelligenceDataNeed", "ProviderCoverageMapping", "ProviderCostBenefit", "ProviderRiskReview", "ProviderActivationGate", "IntelligenceProviderPlan", "build_intelligence_provider_plan"]
