"""Offline subscription planning and consolidation metadata."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

SUBSCRIPTION_STATUSES = ("not_started", "research_only", "trial_candidate", "planned", "active_reference_only", "active_external_not_in_repo", "cancel_candidate", "blocked")
PHASES = ("phase_0_offline_only", "phase_1_manual_imports", "phase_2_live_read_only_intelligence", "phase_3_model_gateway_observability", "phase_4_sales_integrations", "phase_5_accounting_crm_ecommerce_integrations")


def _clean(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {key: _clean(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set)):
        return [_clean(item) for item in value]
    return value


@dataclass(frozen=True)
class SubscriptionOwner:
    department: str
    owner_role: str
    review_cadence: str
    approval_role: str


@dataclass(frozen=True)
class SubscriptionCostBand:
    monthly_min: float
    monthly_max: float
    currency: str
    assumptions: tuple[str, ...]


@dataclass(frozen=True)
class SubscriptionUsageBudget:
    included_usage: str
    expected_usage: str
    monthly_cap: float
    overage_risk: str
    pause_threshold: str


@dataclass(frozen=True)
class SubscriptionCapabilityCoverage:
    capability_ids: tuple[str, ...]
    departments: tuple[str, ...]
    phase: str
    gaps: tuple[str, ...]


@dataclass(frozen=True)
class SubscriptionPlanReference:
    subscription_id: str
    provider_id: str
    plan_name: str
    owner_department: str
    billing_frequency: str
    estimated_monthly_cost_min: float
    estimated_monthly_cost_max: float
    included_usage: str
    overage_risk: str
    cost_driver: str
    capability_coverage: SubscriptionCapabilityCoverage
    required_for_phase: str
    replacement_candidates: tuple[str, ...]
    consolidation_note: str
    approval_required_to_activate: bool
    status: str

    def __post_init__(self) -> None:
        if self.status not in SUBSCRIPTION_STATUSES:
            raise ValueError(f"invalid subscription status: {self.status}")
        if self.required_for_phase not in PHASES:
            raise ValueError(f"invalid subscription phase: {self.required_for_phase}")
        if self.estimated_monthly_cost_min < 0 or self.estimated_monthly_cost_max < self.estimated_monthly_cost_min:
            raise ValueError("invalid subscription cost band")


@dataclass(frozen=True)
class SubscriptionCostEstimate:
    phase: str
    monthly_min: float
    monthly_max: float
    active_subscription_ids: tuple[str, ...]
    excluded_ids: tuple[str, ...]
    assumption_note: str


@dataclass(frozen=True)
class SubscriptionUsageEstimate:
    subscription_id: str
    expected_usage: str
    estimated_overage_cost: float
    confidence: str
    review_trigger: str


@dataclass(frozen=True)
class SubscriptionRenewalPolicy:
    subscription_id: str
    review_days_before_renewal: int
    auto_renew_allowed: bool
    renewal_approval_required: bool
    cancellation_notice_note: str


@dataclass(frozen=True)
class SubscriptionConsolidationRecommendation:
    recommendation_id: str
    provider_ids: tuple[str, ...]
    action: str
    expected_monthly_saving_min: float
    expected_monthly_saving_max: float
    rationale: str
    approval_required: bool


@dataclass(frozen=True)
class SubscriptionRenewalRisk:
    subscription_id: str
    risk_level: str
    reason: str
    mitigation: str


@dataclass(frozen=True)
class SubscriptionCancellationCandidate:
    subscription_id: str
    reason: str
    replacement: str
    estimated_monthly_saving: float
    decision_status: str


@dataclass(frozen=True)
class SubscriptionRegistryReport:
    report_version: str
    generated_at: str
    plans: tuple[SubscriptionPlanReference, ...]
    owners: tuple[SubscriptionOwner, ...]
    cost_bands: tuple[SubscriptionCostBand, ...]
    usage_budgets: tuple[SubscriptionUsageBudget, ...]
    cost_estimates: tuple[SubscriptionCostEstimate, ...]
    usage_estimates: tuple[SubscriptionUsageEstimate, ...]
    renewal_policies: tuple[SubscriptionRenewalPolicy, ...]
    consolidation_recommendations: tuple[SubscriptionConsolidationRecommendation, ...]
    renewal_risks: tuple[SubscriptionRenewalRisk, ...]
    cancellation_candidates: tuple[SubscriptionCancellationCandidate, ...]
    phases: tuple[str, ...]
    safety_summary: dict[str, Any]
    next_best_action: str

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)

    def to_markdown(self) -> str:
        lines = ["# CompanyOS Subscription Registry", "", "## Monthly Cost Plan", "", "| Phase | Low | High | Included references |", "|---|---:|---:|---|"]
        lines.extend(f"| {item.phase} | ${item.monthly_min:.0f} | ${item.monthly_max:.0f} | {', '.join(item.active_subscription_ids) or 'none'} |" for item in self.cost_estimates)
        lines += ["", "## Subscription Plans", "", "| Provider | Plan | Phase | Status | Cost band |", "|---|---|---|---|---|"]
        lines.extend(f"| {item.provider_id} | {item.plan_name} | {item.required_for_phase} | {item.status} | ${item.estimated_monthly_cost_min:.0f}-${item.estimated_monthly_cost_max:.0f} |" for item in self.plans)
        lines += ["", "## Consolidation Recommendations", ""]
        lines.extend(f"- {item.action}: {', '.join(item.provider_ids)} - {item.rationale}" for item in self.consolidation_recommendations)
        lines += ["", "## Safety", "", "- Costs are planning bands, not invoices or spend authority.", "- No subscription was activated, purchased, renewed, or cancelled.", "", "## Next Best Action", "", self.next_best_action, ""]
        return "\n".join(lines)


def _plan(subscription_id: str, provider_id: str, name: str, department: str, phase: str, low: float, high: float, capability: str, replacement: tuple[str, ...] = ()) -> SubscriptionPlanReference:
    coverage = SubscriptionCapabilityCoverage((capability,), (department,), phase, ("No live integration in current mode.",))
    return SubscriptionPlanReference(subscription_id, provider_id, name, department, "monthly", low, high, "Provider-defined usage; not queried.", "Usage overage is unknown until a reviewed plan exists.", "seats, requests, pages, or tokens", coverage, phase, replacement, "Keep as reference-only until owner, budget, and Approval Ledger gate exist.", True, "research_only")


def _base_plans() -> tuple[SubscriptionPlanReference, ...]:
    return (
        _plan("sub-apify", "apify", "Starter / usage band", "intelligence", "phase_2_live_read_only_intelligence", 0, 200, "public_extraction", ("manual_imports",)),
        _plan("sub-dataforseo", "dataforseo", "Search API planning band", "intelligence", "phase_2_live_read_only_intelligence", 50, 500, "serp_keyword_intelligence", ("serpapi",)),
        _plan("sub-serpapi", "serpapi", "Search API planning band", "intelligence", "phase_2_live_read_only_intelligence", 0, 300, "serp_keyword_intelligence", ("dataforseo",)),
        _plan("sub-litellm", "litellm", "Gateway deployment band", "intelligence", "phase_3_model_gateway_observability", 0, 150, "model_routing", ("ollama",)),
        _plan("sub-langfuse", "langfuse", "Trace/eval planning band", "risk_approval", "phase_3_model_gateway_observability", 0, 200, "trace_eval", ("phoenix",)),
        _plan("sub-hubspot", "hubspot", "CRM planning band", "sales", "phase_4_sales_integrations", 0, 500, "crm", ("pipedrive",)),
        _plan("sub-twilio", "twilio", "Messaging planning band", "sales", "phase_4_sales_integrations", 0, 300, "messaging", ()),
        _plan("sub-quickbooks", "quickbooks", "Accounting planning band", "accounting", "phase_5_accounting_crm_ecommerce_integrations", 35, 300, "accounting_sync", ("xero",)),
        _plan("sub-shopify", "shopify", "Commerce platform planning band", "launch", "phase_5_accounting_crm_ecommerce_integrations", 39, 399, "storefront", ("woocommerce", "medusa")),
    )


def build_subscription_registry(*, generated_at: str = "offline-deterministic", phase: str | None = None, seed: Mapping[str, Any] | None = None) -> SubscriptionRegistryReport:
    if phase and phase not in PHASES:
        raise ValueError(f"invalid subscription phase: {phase}")
    plans = _base_plans()
    selected_phase = phase or "phase_0_offline_only"
    owners = tuple(SubscriptionOwner(department, f"{department}_manager", "monthly", "human_operator") for department in ("management", "finance", "intelligence", "risk_approval", "sales", "accounting", "launch"))
    bands = tuple(SubscriptionCostBand(item.estimated_monthly_cost_min, item.estimated_monthly_cost_max, "USD", ("Planning band only.", "No provider pricing query.")) for item in plans)
    usage = tuple(SubscriptionUsageBudget(item.included_usage, "unknown until manual review", item.estimated_monthly_cost_max, item.overage_risk, "pause before overage") for item in plans)
    cost_estimates: list[SubscriptionCostEstimate] = []
    for current in PHASES:
        active = tuple(item.subscription_id for item in plans if item.required_for_phase == current)
        selected = tuple(item for item in plans if item.required_for_phase == current)
        cost_estimates.append(SubscriptionCostEstimate(current, sum(item.estimated_monthly_cost_min for item in selected), sum(item.estimated_monthly_cost_max for item in selected), active, (), "No subscription is active; this is a bounded future planning scenario."))
    estimates = tuple(SubscriptionUsageEstimate(item.subscription_id, "manual review required", 0.0, "unknown", "before activation or renewal") for item in plans)
    renewals = tuple(SubscriptionRenewalPolicy(item.subscription_id, 30, False, True, "Review cancellation terms manually before renewal.") for item in plans)
    consolidation = (SubscriptionConsolidationRecommendation("consolidate-search", ("dataforseo", "serpapi"), "choose one search provider after a bounded benchmark", 0, 250, "Avoid paying for overlapping search coverage before measured use.", True), SubscriptionConsolidationRecommendation("consolidate-model", ("litellm", "ollama"), "start local and add gateway only when spend tracking is needed", 0, 150, "Preserve the offline path and delay gateway overhead.", True))
    risks = tuple(SubscriptionRenewalRisk(item.subscription_id, "medium", "Usage and renewal terms are not live-observed.", "Require owner, cap, and renewal review before activation.") for item in plans)
    cancellations = tuple(SubscriptionCancellationCandidate(item.subscription_id, "No activation evidence or measured workload.", item.replacement_candidates[0] if item.replacement_candidates else "manual_import", item.estimated_monthly_cost_min, "research_only") for item in plans if item.replacement_candidates)
    if selected_phase != "phase_0_offline_only":
        cost_estimates = [item for item in cost_estimates if item.phase == selected_phase] + [item for item in cost_estimates if item.phase != selected_phase]
    return SubscriptionRegistryReport("companyos-subscription-registry-v1", generated_at, plans, owners, bands, usage, tuple(cost_estimates), estimates, renewals, consolidation, risks, cancellations, PHASES, {"read_only": True, "network_calls": False, "mutated": False, "activated": False, "purchased": False, "renewed": False, "cancelled": False}, "Keep subscriptions at research-only until one owner, a cap, an activation approval, and a measurable workload are documented.")


__all__ = ["SUBSCRIPTION_STATUSES", "PHASES", "SubscriptionRegistryReport", "SubscriptionPlanReference", "SubscriptionOwner", "SubscriptionCostBand", "SubscriptionUsageBudget", "SubscriptionCapabilityCoverage", "SubscriptionCostEstimate", "SubscriptionUsageEstimate", "SubscriptionRenewalPolicy", "SubscriptionConsolidationRecommendation", "SubscriptionRenewalRisk", "SubscriptionCancellationCandidate", "build_subscription_registry"]
