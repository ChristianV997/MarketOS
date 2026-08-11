"""Model-routing policy without model providers or calls."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Mapping

MODEL_TIERS = frozenset({"local_low_cost", "cheap_api", "frontier_reasoning", "human_review", "blocked"})
PROVIDERS = frozenset({"openai", "anthropic", "google", "mistral", "groq", "together", "aws_bedrock", "ollama", "llama_cpp", "vllm", "local_stub"})


@dataclass(frozen=True)
class ModelProvider:
    provider_id: str
    name: str
    tier_candidates: tuple[str, ...]
    integration_status: str


@dataclass(frozen=True)
class ModelTier:
    tier_id: str
    name: str
    quality_profile: str
    cost_profile: str
    safety_profile: str


@dataclass(frozen=True)
class ModelRoute:
    task_type: str
    department_owner: str
    recommended_tier: str
    fallback_tier: str
    max_cost_per_run: float
    monthly_budget_cap: float
    quality_requirement: str
    risk_level: str
    human_review_required: bool


@dataclass(frozen=True)
class ModelRoutingPolicy:
    policy_id: str
    default_tier: str
    routes: tuple[ModelRoute, ...]
    blocked_tasks: tuple[str, ...]
    fallback_policy: str


@dataclass(frozen=True)
class ModelBudget:
    budget_id: str
    monthly_cap: float
    per_run_cap: float
    currency: str
    approval_required: bool


@dataclass(frozen=True)
class DepartmentModelBudget:
    department: str
    budget: ModelBudget


@dataclass(frozen=True)
class AgentModelBudget:
    agent_id: str
    budget: ModelBudget


@dataclass(frozen=True)
class ClientModelBudget:
    client_id: str
    budget: ModelBudget


@dataclass(frozen=True)
class CostEstimate:
    task_type: str
    estimated_tokens: int
    estimated_cost: float
    currency: str
    assumption_note: str


@dataclass(frozen=True)
class FallbackPolicy:
    order: tuple[str, ...]
    stop_on_budget_exceeded: bool
    stop_on_safety_failure: bool


@dataclass(frozen=True)
class SpendCapPolicy:
    department_caps: tuple[DepartmentModelBudget, ...]
    agent_caps: tuple[AgentModelBudget, ...]
    client_caps: tuple[ClientModelBudget, ...]
    approval_event: str


@dataclass(frozen=True)
class ModelRouterReport:
    report_version: str
    generated_at: str
    providers: tuple[ModelProvider, ...]
    tiers: tuple[ModelTier, ...]
    policy: ModelRoutingPolicy
    cost_estimates: tuple[CostEstimate, ...]
    spend_caps: SpendCapPolicy
    policy_summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_model_router(*, generated_at: str = "offline-deterministic", seed: Mapping[str, Any] | None = None) -> ModelRouterReport:
    tiers = tuple(ModelTier(item, item.replace("_", " "), "human-reviewed" if item in {"human_review", "frontier_reasoning"} else "bounded", "low" if item == "local_low_cost" else "blocked" if item == "blocked" else "variable", "approval-gated" if item in {"human_review", "blocked"} else "sandbox") for item in sorted(MODEL_TIERS))
    providers = tuple(ModelProvider(provider, provider.replace("_", " ").title(), ("local_low_cost",) if provider in {"local_stub", "ollama", "llama_cpp"} else ("cheap_api", "frontier_reasoning"), "reference_only") for provider in sorted(PROVIDERS))
    routes = (ModelRoute("ledger_categorization", "accounting", "local_low_cost", "cheap_api", .02, 10, "schema_validity", "low", False), ModelRoute("sales_draft_variants", "sales", "cheap_api", "local_low_cost", .20, 40, "safety_boundary_respected", "medium", False), ModelRoute("report_synthesis", "intelligence", "frontier_reasoning", "human_review", 1.50, 150, "groundedness", "high", True), ModelRoute("legal_finance_approval", "risk_approval", "human_review", "blocked", 0.0, 0.0, "human_decision", "high", True), ModelRoute("live_external_action", "operations", "blocked", "human_review", 0.0, 0.0, "no_live_action", "critical", True))
    if isinstance(seed, Mapping):
        overrides = {str(item.get("task_type")): item for item in seed.get("routes", []) if isinstance(item, Mapping)}
        routes = tuple(replace(route, max_cost_per_run=float(overrides.get(route.task_type, {}).get("max_cost_per_run", route.max_cost_per_run))) for route in routes)
    policy = ModelRoutingPolicy("companyos-model-policy-v1", "local_low_cost", routes, ("live_external_action", "unapproved_message", "unapproved_payment", "unapproved_publish"), "Fallback only when within budget and safety gates remain clear.")
    estimates = tuple(CostEstimate(route.task_type, 1000, route.max_cost_per_run, "USD", "Offline estimate; no provider call." ) for route in routes)
    department_caps = tuple(DepartmentModelBudget(department, ModelBudget(f"dept-{department}", 100.0 if department not in {"risk_approval"} else 0.0, 5.0 if department not in {"risk_approval"} else 0.0, "USD", True)) for department in ("management", "finance", "accounting", "sales", "intelligence", "risk_approval", "operations"))
    return ModelRouterReport("companyos-model-router-v1", generated_at, providers, tiers, policy, estimates, SpendCapPolicy(department_caps, (), (), "approval_required_before_cost"), "No model calls are made. Routes are bounded by per-run/monthly caps and stop on safety failure.")


__all__ = ["MODEL_TIERS", "PROVIDERS", "ModelProvider", "ModelTier", "ModelRoute", "ModelRoutingPolicy", "ModelBudget", "DepartmentModelBudget", "AgentModelBudget", "ClientModelBudget", "CostEstimate", "FallbackPolicy", "SpendCapPolicy", "ModelRouterReport", "build_model_router"]
