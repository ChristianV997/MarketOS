"""Deterministic, offline resource and execution governance for CompanyOS."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Sequence

from .model_router import MODEL_TIERS
from .provider_registry import build_provider_registry

ACTION_TYPES = (
    "screen_product_opportunities", "deep_validate_product", "promote_product_candidate", "generate_launch_draft",
    "generate_site_draft", "create_new_brand", "create_new_website", "expand_existing_brand", "request_supplier_proof",
    "prepare_inventory_plan", "increase_inventory_exposure", "generate_creative_batch", "launch_ad_experiment",
    "scale_ad_budget", "kill_ad_experiment", "send_sales_outreach", "generate_sales_sequence", "run_provider_data_pull",
    "run_security_scan", "run_trustops_report", "run_companyos_review", "generate_client_export", "run_frontier_llm_synthesis",
    "run_cheap_llm_task", "run_local_llm_task", "spawn_agent_workflow", "retry_failed_workflow",
)
RESOURCE_TYPES = (
    "llm_tokens", "frontier_llm_budget", "cheap_llm_budget", "local_llm_capacity", "provider_api_budget", "data_provider_budget",
    "ad_spend", "inventory_cash_exposure", "website_build_capacity", "brand_capacity", "creative_generation_capacity",
    "sales_outreach_capacity", "security_scan_capacity", "human_review_capacity", "workflow_runtime", "report_generation_quota", "client_export_quota",
)
DOMAINS = ("intelligence", "supplier", "consumer_attention", "launch", "website_store_funnel", "ads_content", "sales", "finance", "accounting", "management", "trustos", "security", "provider", "model", "client_workspace")
OUTCOMES = ("allow", "warn", "queue", "soft_block", "hard_block", "requires_approval", "requires_finance_review", "requires_management_review", "requires_trustos_review", "requires_workspace_review", "requires_experiment_design", "requires_learning_capture", "kill", "scale", "pause")
MODEL_POLICY_TIERS = ("algorithmic", "local_llm", "cheap_llm", "frontier_llm", "human_review", "blocked")


def _clean(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {key: _clean(getattr(value, key)) for key in value.__dataclass_fields__}
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set)):
        return [_clean(item) for item in value]
    return value


@dataclass(frozen=True)
class ExecutionActionType:
    action_type: str
    domain: str
    description: str
    default_outcome: str
    live_action: bool = False
    def __post_init__(self) -> None:
        if self.action_type not in ACTION_TYPES or self.domain not in DOMAINS or self.default_outcome not in OUTCOMES:
            raise ValueError("invalid execution action")
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class ExecutionResourceType:
    resource_type: str
    unit: str
    description: str
    default_owner_department: str
    def __post_init__(self) -> None:
        if self.resource_type not in RESOURCE_TYPES: raise ValueError("invalid resource type")
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class ResourceBudget:
    resource_type: str
    owner_department: str
    workspace_id: str
    period: str
    budget_limit: float
    used_amount: float
    reserved_amount: float
    unit: str
    hard_cap: float
    soft_cap: float
    requires_approval_above: float
    def __post_init__(self) -> None:
        if self.resource_type not in RESOURCE_TYPES or min(self.budget_limit, self.used_amount, self.reserved_amount, self.hard_cap, self.soft_cap, self.requires_approval_above) < 0:
            raise ValueError("invalid resource budget")
    @property
    def available_amount(self) -> float: return round(max(0.0, self.budget_limit - self.used_amount - self.reserved_amount), 4)
    def to_dict(self) -> dict[str, Any]:
        data = _clean(self); data["available_amount"] = self.available_amount; return data


@dataclass(frozen=True)
class ResourceQuota:
    quota_id: str
    resource_type: str
    owner_department: str
    period: str
    limit: float
    used: float
    reserved: float
    unit: str
    hard_cap: bool
    def __post_init__(self) -> None:
        if self.resource_type not in RESOURCE_TYPES or min(self.limit, self.used, self.reserved) < 0: raise ValueError("invalid resource quota")
    @property
    def available(self) -> float: return max(0.0, self.limit - self.used - self.reserved)
    def to_dict(self) -> dict[str, Any]:
        data = _clean(self); data["available"] = self.available; return data


@dataclass(frozen=True)
class BudgetCheckResult:
    resource_type: str
    requested_amount: float
    available_amount: float
    status: str
    reason: str
    approval_required: bool
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class QuotaCheckResult:
    resource_type: str
    requested_amount: float
    available_amount: float
    status: str
    reason: str
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class ModelSpendPolicy:
    policy_id: str
    tiers: tuple[str, ...]
    routing_rules: tuple[dict[str, Any], ...]
    cost_assumptions: dict[str, float]
    frontier_evidence_threshold: float
    frontier_requires_management_approval: bool
    repeated_low_value_blocked: bool
    human_review_actions: tuple[str, ...]
    blocked_requests: tuple[str, ...]
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class ProviderSpendPolicy:
    policy_id: str
    registered_provider_required: bool
    credential_reference_required_live: bool
    terms_privacy_required: bool
    budget_cap_required: bool
    output_contract_required: bool
    approval_required_paid_or_live: bool
    max_retries: int
    monthly_spend_cap: float
    dry_run_providers_allowed: tuple[str, ...]
    raw_payload_missing_outcome: str
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class DepartmentCapacityPolicy:
    policy_id: str
    department: str
    capacity_resource: str
    monthly_limit: float
    reserved_for_approvals: float
    escalation_threshold: float
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class PortfolioPolicy:
    policy_id: str
    max_raw_opportunities_per_cycle: int
    max_deep_validations_per_cycle: int
    max_promoted_candidates_per_cycle: int
    max_launch_drafts_per_cycle: int
    max_new_sites_per_cycle: int
    max_new_brands_per_cycle: int
    max_active_products: int
    max_active_categories: int
    max_inventory_exposure: float
    prefer_existing_brand_expansion: bool
    minimum_opportunity_score: float
    minimum_supplier_score: float
    minimum_attention_score: float
    minimum_unit_economics_score: float
    minimum_portfolio_fit_score: float
    strategic_rule: str
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class KillScaleRule:
    rule_id: str
    experiment_id: str
    success_metric: str
    kill_threshold: float
    scale_threshold: float
    sample_size_target: int
    max_scale_increment: float
    max_iterations: int
    kill_action: str
    scale_action: str
    pause_action: str
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class ExperimentPolicy:
    policy_id: str
    required_fields: tuple[str, ...]
    rules: tuple[str, ...]
    default_max_scale_increment: float
    large_scale_requires_approval: bool
    learning_required_before_iteration: bool
    kill_scale_rules: tuple[KillScaleRule, ...]
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class RunawayGuardPolicy:
    policy_id: str
    max_workflow_steps: int
    max_retries: int
    max_child_tasks: int
    max_spawned_agents: int
    max_provider_calls: int
    max_llm_calls: int
    max_frontier_llm_calls: int
    max_output_files: int
    max_runtime_seconds: int
    max_budget_per_run: float
    max_repeated_similar_outputs: int
    stop_conditions: tuple[str, ...]
    outputs: tuple[str, ...]
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class LearningCaptureRequirement:
    required: bool
    learning_type: str
    source_action_id: str
    success_metric: str
    failure_reason_required: bool
    winner_attributes_required: bool
    loser_attributes_required: bool
    do_not_repeat_rule_required: bool
    next_iteration_required: bool
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class CrossDepartmentDependency:
    dependency_id: str
    action_type: str
    required_departments: tuple[str, ...]
    required_checks: tuple[str, ...]
    approval_owner: str
    blocked_without: tuple[str, ...]
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class ExecutionPriorityScore:
    strategic_fit: float
    evidence_strength: float
    revenue_or_learning_value: float
    urgency: float
    total: float
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class ExecutionRiskScore:
    financial_risk: float
    action_risk: float
    complexity_risk: float
    trust_risk: float
    total: float
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class ExecutionApprovalRequirement:
    required: bool
    approval_type: str
    approver_role: str
    reason: str
    linked_action: str
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class ExecutionDecisionRequest:
    request_id: str
    action_type: str
    domain: str
    owner_department: str
    workspace_id: str
    requested_amount: float = 0.0
    resource_type: str = "workflow_runtime"
    model_tier: str = "algorithmic"
    provider_id: str = ""
    evidence_score: float = 1.0
    opportunity_score: float = 1.0
    supplier_score: float = 1.0
    attention_score: float = 1.0
    unit_economics_score: float = 1.0
    portfolio_fit_score: float = 1.0
    existing_brand_fit: bool = False
    supplier_proof: bool = True
    terms_privacy_complete: bool = True
    output_contract_tested: bool = True
    registered_provider: bool = True
    approval_state: str = "not_requested"
    trustos_decision: str = "allow"
    workspace_decision: str = "allow"
    hypothesis: str = ""
    success_metric: str = ""
    kill_threshold: float | None = None
    scale_threshold: float | None = None
    sample_size: int = 0
    sample_size_target: int = 0
    metric_value: float | None = None
    learning_captured: bool = True
    previous_learning_required: bool = False
    retry_count: int = 0
    workflow_steps: int = 0
    child_tasks: int = 0
    spawned_agents: int = 0
    provider_calls: int = 0
    llm_calls: int = 0
    frontier_llm_calls: int = 0
    repeated_similar_outputs: int = 0
    max_scale_increment: float = 0.2
    def __post_init__(self) -> None:
        if self.action_type not in ACTION_TYPES or self.resource_type not in RESOURCE_TYPES or self.model_tier not in MODEL_POLICY_TIERS:
            raise ValueError("invalid execution decision request")
        if self.requested_amount < 0: raise ValueError("requested amount cannot be negative")
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class ExecutionDecisionResult:
    request_id: str
    action_type: str
    outcome: str
    reason: str
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    approvals: tuple[ExecutionApprovalRequirement, ...]
    budget_checks: tuple[BudgetCheckResult, ...]
    quota_checks: tuple[QuotaCheckResult, ...]
    priority_score: ExecutionPriorityScore
    risk_score: ExecutionRiskScore
    dependencies: tuple[CrossDepartmentDependency, ...]
    learning_requirement: LearningCaptureRequirement
    next_best_action: str
    simulated_only: bool = True
    def __post_init__(self) -> None:
        if self.outcome not in OUTCOMES or not self.simulated_only: raise ValueError("governor decisions are offline simulations")
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class ExecutionGovernorSafetySummary:
    read_only: bool = True
    network_calls: bool = False
    model_calls: bool = False
    provider_calls: bool = False
    ads_launched: bool = False
    sites_published: bool = False
    orders_created: bool = False
    payments_created: bool = False
    messages_sent: bool = False
    auth_calls: bool = False
    database_writes: bool = False
    tenant_created: bool = False
    credentials_present: bool = False
    client_data_present: bool = False
    artifacts_written: bool = False
    def __post_init__(self) -> None:
        if not self.read_only or any(value for key, value in _clean(self).items() if key != "read_only"): raise ValueError("governor must remain offline and read-only")
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class ResourceExecutionGovernorReport:
    report_version: str
    generated_at: str
    actions: tuple[ExecutionActionType, ...]
    resources: tuple[ExecutionResourceType, ...]
    decisions: tuple[ExecutionDecisionResult, ...]
    budgets: tuple[ResourceBudget, ...]
    quotas: tuple[ResourceQuota, ...]
    model_policy: ModelSpendPolicy
    provider_policy: ProviderSpendPolicy
    department_capacity_policies: tuple[DepartmentCapacityPolicy, ...]
    portfolio_policy: PortfolioPolicy
    experiment_policy: ExperimentPolicy
    runaway_policy: RunawayGuardPolicy
    learning_requirements: tuple[LearningCaptureRequirement, ...]
    dependencies: tuple[CrossDepartmentDependency, ...]
    safety_summary: ExecutionGovernorSafetySummary
    next_best_action: str
    def to_dict(self) -> dict[str, Any]:
        data = _clean(self)
        outcomes = [item.outcome for item in self.decisions]
        data.update({"decision_count": len(self.decisions), "allowed_count": outcomes.count("allow"), "warn_count": outcomes.count("warn"), "queued_count": outcomes.count("queue"), "soft_block_count": outcomes.count("soft_block"), "hard_block_count": outcomes.count("hard_block"), "approval_required_count": outcomes.count("requires_approval"), "kill_count": outcomes.count("kill"), "scale_count": outcomes.count("scale"), "pause_count": outcomes.count("pause"), "budget_count": len(self.budgets), "quota_count": len(self.quotas), "portfolio_policy_count": 1, "experiment_policy_count": 1, "runaway_policy_count": 1, "model_policy_count": 1, "provider_policy_count": 1, "cross_department_dependency_count": len(self.dependencies), "top_blockers": [blocker for item in self.decisions for blocker in item.blockers][:10], "top_budget_constraints": [item.reason for decision in self.decisions for item in decision.budget_checks if item.status != "available"][:10], "top_portfolio_constraints": [item.reason for item in self.decisions if item.action_type in {"create_new_brand", "create_new_website", "promote_product_candidate"} and item.blockers][:10], "top_model_cost_constraints": [item.reason for item in self.decisions if item.action_type.startswith("run_") and item.blockers][:10], "top_provider_constraints": [item.reason for item in self.decisions if item.action_type == "run_provider_data_pull" and item.blockers][:10]})
        return data
    def to_markdown(self) -> str:
        data = self.to_dict(); lines = ["# Resource & Execution Governor", "", "## Executive Summary", "", f"- Decisions: **{data['decision_count']}**", f"- Allowed: **{data['allowed_count']}**", f"- Hard blocked: **{data['hard_block_count']}**", f"- Approval/review outcomes: **{data['approval_required_count']}**", "- Mode: **offline deterministic simulation**", "", "## Decision Outcomes", "", "| Action | Outcome | Reason |", "|---|---|---|"]
        lines.extend(f"| {item.action_type} | **{item.outcome}** | {item.reason} |" for item in self.decisions)
        lines += ["", "## Budget and Quota Controls", "", *[f"- `{item.resource_type}`: {item.available_amount:.2f} {item.unit} available; hard cap {item.hard_cap:.2f}." for item in self.budgets], "", "## Model Spend Policy", "", "Algorithmic scoring is preferred; local/cheap models handle bounded drafts; frontier reasoning requires evidence, budget, and management review; live action is blocked.", "", "## Provider/API Spend Policy", "", "Registered provider, credential reference, terms/privacy review, output contract, budget cap, and approval are required for future live calls.", "", "## Portfolio Governor", "", self.portfolio_policy.strategic_rule, "", "## Experiment Governor", "", *[f"- `{item.rule_id}`: kill below {item.kill_threshold}; scale above {item.scale_threshold}; max increment {item.max_scale_increment:.0%}." for item in self.experiment_policy.kill_scale_rules], "", "## Runaway Guard", "", f"Max steps {self.runaway_policy.max_workflow_steps}; retries {self.runaway_policy.max_retries}; agents {self.runaway_policy.max_spawned_agents}; provider calls {self.runaway_policy.max_provider_calls}.", "", "## Cross-Department Decision Wiring", "", *[f"- `{item.action_type}` requires: {', '.join(item.required_departments)}." for item in self.dependencies], "", "## Learning Capture Requirements", "", *[f"- `{item.learning_type}` from `{item.source_action_id}`: required={item.required}." for item in self.learning_requirements], "", "## Safety Boundaries", "", "No model/provider calls, ads, publishing, orders, payments, messaging, auth, database writes, tenant creation, client data, or artifacts by default.", "", "## Next Best Action", "", self.next_best_action, ""]
        return "\n".join(lines)


def _action_catalog() -> tuple[ExecutionActionType, ...]:
    domains = {"screen_product_opportunities": "intelligence", "deep_validate_product": "intelligence", "promote_product_candidate": "launch", "generate_launch_draft": "launch", "generate_site_draft": "website_store_funnel", "create_new_brand": "management", "create_new_website": "website_store_funnel", "expand_existing_brand": "launch", "request_supplier_proof": "supplier", "prepare_inventory_plan": "finance", "increase_inventory_exposure": "finance", "generate_creative_batch": "ads_content", "launch_ad_experiment": "ads_content", "scale_ad_budget": "ads_content", "kill_ad_experiment": "ads_content", "send_sales_outreach": "sales", "generate_sales_sequence": "sales", "run_provider_data_pull": "provider", "run_security_scan": "security", "run_trustops_report": "trustos", "run_companyos_review": "management", "generate_client_export": "client_workspace", "run_frontier_llm_synthesis": "model", "run_cheap_llm_task": "model", "run_local_llm_task": "model", "spawn_agent_workflow": "management", "retry_failed_workflow": "management"}
    return tuple(ExecutionActionType(item, domains[item], item.replace("_", " ").title(), "allow" if item in {"screen_product_opportunities", "run_local_llm_task", "run_companyos_review", "run_trustops_report", "generate_launch_draft", "generate_site_draft"} else "requires_approval") for item in ACTION_TYPES)


def _resource_catalog() -> tuple[ExecutionResourceType, ...]:
    units = {"llm_tokens": "tokens", "frontier_llm_budget": "USD", "cheap_llm_budget": "USD", "local_llm_capacity": "runs", "provider_api_budget": "USD", "data_provider_budget": "USD", "ad_spend": "USD", "inventory_cash_exposure": "USD", "website_build_capacity": "projects", "brand_capacity": "brands", "creative_generation_capacity": "batches", "sales_outreach_capacity": "drafts", "security_scan_capacity": "runs", "human_review_capacity": "reviews", "workflow_runtime": "seconds", "report_generation_quota": "reports", "client_export_quota": "exports"}
    return tuple(ExecutionResourceType(item, units[item], item.replace("_", " ").title(), "finance" if any(word in item for word in ("budget", "spend", "exposure")) else "management") for item in RESOURCE_TYPES)


def _default_budgets() -> tuple[ResourceBudget, ...]:
    values = {"frontier_llm_budget": (100.0, 0.0, 0.0, 100.0, 75.0, 25.0), "cheap_llm_budget": (50.0, 0.0, 0.0, 50.0, 40.0, 10.0), "provider_api_budget": (25.0, 0.0, 0.0, 25.0, 15.0, 5.0), "data_provider_budget": (25.0, 0.0, 0.0, 25.0, 15.0, 5.0), "ad_spend": (100.0, 0.0, 0.0, 100.0, 50.0, 25.0), "inventory_cash_exposure": (250.0, 0.0, 0.0, 250.0, 150.0, 100.0), "website_build_capacity": (1.0, 0.0, 0.0, 1.0, 1.0, 1.0), "brand_capacity": (1.0, 0.0, 0.0, 1.0, 1.0, 1.0), "creative_generation_capacity": (10.0, 0.0, 0.0, 10.0, 8.0, 5.0), "report_generation_quota": (20.0, 0.0, 0.0, 20.0, 15.0, 10.0), "client_export_quota": (5.0, 0.0, 0.0, 5.0, 4.0, 3.0)}
    return tuple(ResourceBudget(resource, "finance", "internal-companyos", "monthly", values[resource][0], values[resource][1], values[resource][2], "USD" if "budget" in resource or resource in {"provider_api_budget", "data_provider_budget", "ad_spend", "inventory_cash_exposure"} else "units", values[resource][3], values[resource][4], values[resource][5]) for resource in values)


def _portfolio() -> PortfolioPolicy:
    return PortfolioPolicy("portfolio-v1", 50, 5, 2, 2, 1, 1, 3, 3, 250.0, True, .60, .60, .60, .60, .60, "Many ideas enter. Few become candidates. Fewer become experiments. Only winners get scaled; losers become learning data.")


def _model_policy() -> ModelSpendPolicy:
    return ModelSpendPolicy("model-spend-governor-v1", MODEL_POLICY_TIERS, (("deterministic_scoring", "algorithmic"), ("structured_extraction", "local_llm_or_cheap_llm"), ("routine_report_drafting", "cheap_llm"), ("high_stakes_synthesis", "frontier_llm_or_human_review"), ("external_action_approval", "human_review"), ("live_action_execution", "blocked")), {"algorithmic": 0.0, "local_llm": 0.01, "cheap_llm": 0.10, "frontier_llm": 2.0, "human_review": 25.0}, .75, True, True, ("legal", "tax", "security", "external_action"), ("credential_extraction", "hidden_prompt_request", "unbounded_user_task"))


def _provider_policy() -> ProviderSpendPolicy:
    return ProviderSpendPolicy("provider-spend-governor-v1", True, True, True, True, True, True, 2, 25.0, ("dataforseo", "apify", "serpapi", "manual_import"), "hard_block")


def _experiment_policy() -> ExperimentPolicy:
    rule = KillScaleRule("default-ad-test-rule", "experiment-placeholder", "conversion_rate", .02, .05, 100, .20, 3, "kill_ad_experiment", "scale_ad_budget", "pause")
    return ExperimentPolicy("experiment-governor-v1", ("hypothesis", "budget_cap", "sample_size_target", "success_metric", "kill_threshold", "scale_threshold", "learning_required"), ("No experiment without a hypothesis and cap.", "No scale without evidence.", "Kill losers after sufficient sample.", "Pause inconclusive tests.", "Capture learning before iteration."), .20, True, True, (rule,))


def _runaway() -> RunawayGuardPolicy:
    return RunawayGuardPolicy("runaway-guard-v1", 25, 2, 10, 3, 5, 10, 2, 20, 300, 25.0, 2, ("unbounded retry", "step cap exceeded", "child-task cap exceeded", "provider retry loop", "frontier repetition without new evidence", "same output without new evidence"), ("pause_and_summarize", "request_approval", "record_risk", "recommend_next_best_action"))


def _dependencies() -> tuple[CrossDepartmentDependency, ...]:
    return (CrossDepartmentDependency("dep-product-promotion", "promote_product_candidate", ("intelligence", "supplier", "consumer_attention", "finance", "risk_approval", "management"), ("opportunity evidence", "supplier feasibility", "attention signal", "unit economics", "TrustOS clear", "priority assigned"), "management", ("supplier proof", "budget", "approval")), CrossDepartmentDependency("dep-new-website", "create_new_website", ("launch", "website_store_funnel", "finance", "risk_approval", "client_workspace"), ("portfolio fit", "build capacity", "public launch blockers reviewed", "workspace boundary"), "management", ("portfolio fit", "finance review", "TrustOS review")), CrossDepartmentDependency("dep-ads", "launch_ad_experiment", ("consumer_attention", "finance", "risk_approval", "trustos"), ("hypothesis", "measurement", "kill/scale rule", "claims review", "budget cap"), "marketing_manager", ("learning capture", "approval")), CrossDepartmentDependency("dep-model", "run_frontier_llm_synthesis", ("model", "finance", "management", "trustos"), ("evidence threshold", "model budget", "runaway guard", "risk review"), "management", ("budget", "approval")), CrossDepartmentDependency("dep-provider", "run_provider_data_pull", ("provider", "finance", "risk_approval", "trustos"), ("registered provider", "credential reference", "terms/privacy", "output contract", "budget"), "risk_approval", ("approval", "live mode")), CrossDepartmentDependency("dep-client-export", "generate_client_export", ("client_workspace", "risk_approval", "management"), ("isolation policy", "leakage check", "approved projection"), "risk_approval", ("workspace review", "internal exclusion")))


def _learning(action: str, required: bool | None = None) -> LearningCaptureRequirement:
    learning_type = "creative_test" if "creative" in action or "ad_" in action else "product_validation" if "product" in action else "provider_run" if "provider" in action else "model_routing" if "llm" in action else "trustos_review" if "trust" in action else "companyos_review"
    return LearningCaptureRequirement(required if required is not None else action in {"launch_ad_experiment", "generate_creative_batch", "deep_validate_product", "run_provider_data_pull", "run_frontier_llm_synthesis"}, learning_type, action, "success_metric_or_review_result", True, True, True, True, True)


def _budget_check(request: ExecutionDecisionRequest, budgets: Sequence[ResourceBudget]) -> BudgetCheckResult:
    budget = next((item for item in budgets if item.resource_type == request.resource_type), None)
    if budget is None: return BudgetCheckResult(request.resource_type, request.requested_amount, 0.0, "missing", "no budget is registered for this resource", True)
    if request.requested_amount > budget.hard_cap or request.requested_amount > budget.available_amount: return BudgetCheckResult(request.resource_type, request.requested_amount, budget.available_amount, "blocked", "hard cap or available budget exceeded", True)
    if request.requested_amount > budget.soft_cap: return BudgetCheckResult(request.resource_type, request.requested_amount, budget.available_amount, "soft_cap", "soft cap exceeded; finance review required", True)
    return BudgetCheckResult(request.resource_type, request.requested_amount, budget.available_amount, "available", "within budget", request.requested_amount > budget.requires_approval_above)


def _quota_check(request: ExecutionDecisionRequest) -> QuotaCheckResult:
    limits = {"screen_product_opportunities": (50, 0), "deep_validate_product": (5, 0), "promote_product_candidate": (2, 0), "generate_launch_draft": (2, 0), "generate_site_draft": (1, 0), "create_new_website": (1, 0), "create_new_brand": (1, 0), "generate_creative_batch": (10, 0), "client_export_quota": (5, 0)}
    limit, used = limits.get(request.action_type, (25, 0)); amount = 1.0
    if used + amount > limit: return QuotaCheckResult(request.resource_type, amount, 0.0, "blocked", "action quota exceeded")
    return QuotaCheckResult(request.resource_type, amount, float(limit - used - amount), "available", "within action quota")


def _scores(request: ExecutionDecisionRequest) -> tuple[ExecutionPriorityScore, ExecutionRiskScore]:
    priority = round((request.opportunity_score + request.evidence_score + request.portfolio_fit_score + request.attention_score) / 4, 3)
    risk = round((request.requested_amount > 25) * .4 + (request.model_tier == "frontier_llm") * .3 + (request.provider_id != "") * .2 + (request.workspace_id != "internal-companyos") * .1, 3)
    return ExecutionPriorityScore(request.portfolio_fit_score, request.evidence_score, request.opportunity_score, request.attention_score, priority), ExecutionRiskScore(float(request.requested_amount > 25), float(request.action_type in {"launch_ad_experiment", "scale_ad_budget", "increase_inventory_exposure"}), float(request.spawned_agents > 2 or request.retry_count > 2), risk, round((float(request.requested_amount > 25) + float(request.action_type in {"launch_ad_experiment", "scale_ad_budget", "increase_inventory_exposure"}) + float(request.spawned_agents > 2 or request.retry_count > 2) + risk) / 4, 3))


def evaluate_execution_request(request: ExecutionDecisionRequest, *, budgets: Sequence[ResourceBudget] = (), portfolio: PortfolioPolicy | None = None, runaway: RunawayGuardPolicy | None = None, provider_policy: ProviderSpendPolicy | None = None) -> ExecutionDecisionResult:
    budgets = tuple(budgets) or _default_budgets(); portfolio = portfolio or _portfolio(); runaway = runaway or _runaway(); provider_policy = provider_policy or _provider_policy()
    budget = _budget_check(request, budgets); quota = _quota_check(request); blockers: list[str] = []; warnings: list[str] = []; approvals: list[ExecutionApprovalRequirement] = []
    deps = tuple(item for item in _dependencies() if item.action_type == request.action_type)
    if budget.status == "blocked": blockers.append(budget.reason)
    elif budget.status == "soft_cap": approvals.append(ExecutionApprovalRequirement(True, "budget_cap", "finance_manager", budget.reason, request.action_type))
    if quota.status == "blocked": blockers.append(quota.reason)
    if request.trustos_decision in {"hard_block", "blocked"}: blockers.append("TrustOS gate is blocked")
    if request.workspace_decision in {"hard_block", "blocked"}: blockers.append("client workspace gate is blocked")
    if request.retry_count > runaway.max_retries or request.workflow_steps > runaway.max_workflow_steps or request.child_tasks > runaway.max_child_tasks or request.spawned_agents > runaway.max_spawned_agents or request.provider_calls > runaway.max_provider_calls or request.llm_calls > runaway.max_llm_calls or request.frontier_llm_calls > runaway.max_frontier_llm_calls or request.repeated_similar_outputs > runaway.max_repeated_similar_outputs:
        blockers.append("runaway guard cap exceeded")
    if request.action_type == "deep_validate_product" and request.opportunity_score < portfolio.minimum_opportunity_score: blockers.append("opportunity score below portfolio threshold")
    if request.action_type == "promote_product_candidate" and any(score < threshold for score, threshold in ((request.opportunity_score, portfolio.minimum_opportunity_score), (request.supplier_score, portfolio.minimum_supplier_score), (request.attention_score, portfolio.minimum_attention_score), (request.unit_economics_score, portfolio.minimum_unit_economics_score), (request.portfolio_fit_score, portfolio.minimum_portfolio_fit_score))): blockers.append("candidate is below a portfolio score threshold")
    if request.action_type in {"create_new_brand", "create_new_website"} and request.existing_brand_fit and portfolio.prefer_existing_brand_expansion: blockers.append("existing brand/category fit should absorb this work")
    if request.action_type == "increase_inventory_exposure" and not request.supplier_proof: blockers.append("supplier proof is required before inventory exposure")
    if request.action_type == "launch_ad_experiment":
        missing = [name for name, value in (("hypothesis", request.hypothesis), ("success metric", request.success_metric), ("kill threshold", request.kill_threshold is not None), ("budget cap", request.requested_amount > 0)) if not value]
        if missing: blockers.append("experiment design missing: " + ", ".join(missing))
        elif request.approval_state != "approved": approvals.append(ExecutionApprovalRequirement(True, "ad_launch", "marketing_manager", "ad experiments require human approval", request.action_type))
    if request.action_type == "scale_ad_budget":
        if request.metric_value is None or request.scale_threshold is None: blockers.append("scale evidence is missing")
        elif request.metric_value < request.scale_threshold: blockers.append("scale threshold not met")
        elif request.max_scale_increment > .30: approvals.append(ExecutionApprovalRequirement(True, "scale_budget", "finance_manager", "scale increment exceeds controlled limit", request.action_type))
    if request.action_type == "kill_ad_experiment" and request.metric_value is not None and request.kill_threshold is not None and request.sample_size >= request.sample_size_target and request.metric_value < request.kill_threshold: return ExecutionDecisionResult(request.request_id, request.action_type, "kill", "kill threshold met after sufficient sample", tuple(blockers), tuple(warnings), tuple(approvals), (budget,), (quota,), *_scores(request), deps, _learning(request.action_type, True), "record failure reason and do-not-repeat rule")
    if request.action_type == "run_provider_data_pull":
        if not request.registered_provider: blockers.append("provider is not registered")
        if not request.terms_privacy_complete: blockers.append("terms/privacy review is incomplete")
        if not request.output_contract_tested: blockers.append("provider output contract is not tested")
        if request.approval_state != "approved": approvals.append(ExecutionApprovalRequirement(True, "provider_call", "human_operator", "provider calls require Approval Ledger authorization", request.action_type))
    if request.action_type == "run_frontier_llm_synthesis":
        if request.evidence_score < .75: blockers.append("frontier evidence threshold not met")
        if request.approval_state != "approved": approvals.append(ExecutionApprovalRequirement(True, "model_spend", "management_manager", "frontier reasoning requires management approval", request.action_type))
    if request.action_type == "spawn_agent_workflow" and request.spawned_agents >= runaway.max_spawned_agents: blockers.append("spawned-agent cap exceeded")
    if request.previous_learning_required and not request.learning_captured: blockers.append("required learning has not been captured")
    if request.action_type == "generate_client_export" and request.workspace_decision != "allow": blockers.append("workspace isolation review is required")
    if request.model_tier == "blocked": blockers.append("model tier is blocked")
    if request.action_type in {"send_sales_outreach", "launch_ad_experiment", "scale_ad_budget", "create_new_website", "create_new_brand", "increase_inventory_exposure"} and request.approval_state != "approved": approvals.append(ExecutionApprovalRequirement(True, "approval_ledger", "human_operator", "external-world or material-capital action requires approval", request.action_type))
    if request.action_type == "generate_creative_batch" and request.previous_learning_required and not request.learning_captured: blockers.append("previous creative learning is missing")
    priority, risk = _scores(request)
    if blockers: outcome = "hard_block" if any("runaway" in item or "terms/privacy" in item or "TrustOS" in item or "workspace" in item or "provider output" in item for item in blockers) else "soft_block"
    elif budget.status == "soft_cap": outcome = "requires_finance_review"
    elif approvals: outcome = "requires_approval"
    elif request.action_type == "scale_ad_budget" and request.metric_value is not None and request.scale_threshold is not None and request.metric_value >= request.scale_threshold and request.approval_state == "approved": outcome = "scale"
    elif request.action_type in {"run_security_scan", "run_companyos_review", "run_trustops_report", "run_local_llm_task", "run_cheap_llm_task", "screen_product_opportunities"}: outcome = "allow"
    else: outcome = "queue"
    return ExecutionDecisionResult(request.request_id, request.action_type, outcome, blockers[0] if blockers else approvals[0].reason if approvals else "within policy and capacity", tuple(dict.fromkeys(blockers)), tuple(dict.fromkeys(warnings)), tuple(approvals), (budget,), (quota,), priority, risk, deps, _learning(request.action_type), "resolve blockers, then re-evaluate" if blockers else "record outcome and capture learning")


def _default_requests() -> tuple[ExecutionDecisionRequest, ...]:
    return (ExecutionDecisionRequest("decision-screen", "screen_product_opportunities", "intelligence", "intelligence", "internal-companyos", 0, "report_generation_quota"), ExecutionDecisionRequest("decision-website", "create_new_website", "website_store_funnel", "launch", "internal-companyos", 1, "website_build_capacity", existing_brand_fit=True), ExecutionDecisionRequest("decision-ad", "launch_ad_experiment", "ads_content", "consumer_attention", "internal-companyos", 25, "ad_spend"), ExecutionDecisionRequest("decision-frontier", "run_frontier_llm_synthesis", "model", "management", "internal-companyos", 5, "frontier_llm_budget", "frontier_llm", evidence_score=.40), ExecutionDecisionRequest("decision-provider", "run_provider_data_pull", "provider", "intelligence", "internal-companyos", 10, "data_provider_budget", provider_id="dataforseo", terms_privacy_complete=False, approval_state="not_requested"), ExecutionDecisionRequest("decision-runaway", "spawn_agent_workflow", "management", "operations", "internal-companyos", 0, "workflow_runtime", spawned_agents=5), ExecutionDecisionRequest("decision-kill", "kill_ad_experiment", "ads_content", "consumer_attention", "internal-companyos", 0, "ad_spend", metric_value=.01, kill_threshold=.02, sample_size=120, sample_size_target=100), ExecutionDecisionRequest("decision-scale", "scale_ad_budget", "ads_content", "finance", "internal-companyos", 20, "ad_spend", metric_value=.06, scale_threshold=.05, max_scale_increment=.20, approval_state="approved"))


def build_resource_execution_governor_report(*, generated_at: str = "offline-deterministic", requests: Sequence[ExecutionDecisionRequest] | None = None, context: Mapping[str, Any] | None = None) -> ResourceExecutionGovernorReport:
    context = context or {}; budgets = _default_budgets(); portfolio = _portfolio(); runaway = _runaway(); provider_policy = _provider_policy()
    requests = tuple(requests or _default_requests())
    decisions = tuple(evaluate_execution_request(item, budgets=budgets, portfolio=portfolio, runaway=runaway, provider_policy=provider_policy) for item in requests)
    requirements = tuple(_learning(item) for item in ACTION_TYPES)
    return ResourceExecutionGovernorReport("resource-execution-governor-v1", generated_at, _action_catalog(), _resource_catalog(), decisions, budgets, tuple(ResourceQuota(f"quota-{item}", item, "management", "cycle", 50 if item == "report_generation_quota" else 10, 0, 0, "units", True) for item in ("report_generation_quota", "client_export_quota", "workflow_runtime")), _model_policy(), provider_policy, (DepartmentCapacityPolicy("capacity-finance", "finance", "frontier_llm_budget", 100, 25, 75), DepartmentCapacityPolicy("capacity-management", "management", "workflow_runtime", 100, 20, 80)), portfolio, _experiment_policy(), runaway, requirements, _dependencies(), ExecutionGovernorSafetySummary(), "Review hard blockers and approve only bounded, evidenced actions; capture learning before the next experiment.")


def request_from_mapping(payload: Mapping[str, Any]) -> ExecutionDecisionRequest:
    allowed = set(ExecutionDecisionRequest.__dataclass_fields__)
    return ExecutionDecisionRequest(**{key: value for key, value in payload.items() if key in allowed})


def apply_learning_influence(request: ExecutionDecisionRequest, influence: Mapping[str, Any] | None = None, *, apply_model_routing_lessons: bool = False, apply_provider_routing_lessons: bool = False) -> ExecutionDecisionRequest:
    """Fold an optional, externally-derived learning signal into the
    inputs `evaluate_execution_request` already consumes, without changing
    that function at all.

    `influence` is a plain `Mapping` -- e.g. the dict returned by
    `evaluation.companyos.learning_ledger.LearningGovernorInfluence.to_governor_context()`
    -- rather than a typed import, so this module never depends on the
    Learning Ledger's types and the Learning Ledger never depends on this
    module's types. Four keys can only ever *tighten* the request, by
    reusing the existing `previous_learning_required` gate
    `evaluate_execution_request` already enforces at line-level as
    "required learning has not been captured": `do_not_repeat_blocked`,
    `hold_or_avoid`, `trustos_recurrence_blocked`, and
    `kill_blocks_resumption` (a single recorded kill, unlike the other
    three, needs no repetition to force this). Two more keys are read only
    when the caller opts in: `recommended_model_tier`, with
    `apply_model_routing_lessons` (planning metadata -- ignored unless
    already one of `MODEL_POLICY_TIERS`), and `recommended_provider_id` /
    `avoid_provider_ids`, with `apply_provider_routing_lessons` -- and even
    then only ever to move the request *away* from a provider the
    influence itself flags as blocked for this action, never to
    second-guess an otherwise-fine provider choice.

    This function never touches `trustos_decision`, `workspace_decision`,
    `approval_state`, budgets, quotas, or provider readiness flags
    (`registered_provider`, `terms_privacy_complete`,
    `output_contract_tested`): those hard gates stay under
    `evaluate_execution_request`'s exclusive, unmodified control, so a
    positive learning signal -- never even read here -- cannot bypass
    them, and a negative one can only ever ask for more learning capture
    or plan around a different tier/provider, never execute, approve, or
    call anything itself.

    Absent or empty `influence` returns `request` unchanged, so existing
    callers that never pass a learning context see no behavior change.
    """
    if not influence: return request
    do_not_repeat_blocked = bool(influence.get("do_not_repeat_blocked", False))
    hold_or_avoid = bool(influence.get("hold_or_avoid", False))
    trustos_recurrence_blocked = bool(influence.get("trustos_recurrence_blocked", False))
    kill_blocks_resumption = bool(influence.get("kill_blocks_resumption", False))
    previous_learning_required = request.previous_learning_required or do_not_repeat_blocked or hold_or_avoid or trustos_recurrence_blocked or kill_blocks_resumption
    model_tier = request.model_tier
    if apply_model_routing_lessons:
        recommended_model_tier = str(influence.get("recommended_model_tier", "") or "")
        if recommended_model_tier in MODEL_POLICY_TIERS: model_tier = recommended_model_tier
    provider_id = request.provider_id
    if apply_provider_routing_lessons:
        recommended_provider_id = str(influence.get("recommended_provider_id", "") or "")
        avoid_provider_ids = tuple(influence.get("avoid_provider_ids", ()) or ())
        if recommended_provider_id and request.provider_id in avoid_provider_ids: provider_id = recommended_provider_id
    if previous_learning_required == request.previous_learning_required and model_tier == request.model_tier and provider_id == request.provider_id: return request
    return replace(request, previous_learning_required=previous_learning_required, model_tier=model_tier, provider_id=provider_id)


__all__ = ["ACTION_TYPES", "RESOURCE_TYPES", "DOMAINS", "OUTCOMES", "MODEL_POLICY_TIERS", "ExecutionActionType", "ExecutionResourceType", "ResourceBudget", "ResourceQuota", "BudgetCheckResult", "QuotaCheckResult", "ModelSpendPolicy", "ProviderSpendPolicy", "DepartmentCapacityPolicy", "PortfolioPolicy", "KillScaleRule", "ExperimentPolicy", "RunawayGuardPolicy", "LearningCaptureRequirement", "CrossDepartmentDependency", "ExecutionPriorityScore", "ExecutionRiskScore", "ExecutionApprovalRequirement", "ExecutionDecisionRequest", "ExecutionDecisionResult", "ExecutionGovernorSafetySummary", "ResourceExecutionGovernorReport", "evaluate_execution_request", "build_resource_execution_governor_report", "request_from_mapping", "apply_learning_influence"]
