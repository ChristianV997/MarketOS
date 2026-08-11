"""Curated CompanyOS agent definitions; no agents are executed here."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Iterable, Mapping

RUN_MODES = frozenset({"draft_only", "read_only", "sandbox", "approval_required", "blocked"})


@dataclass(frozen=True)
class AgentRole:
    role_id: str
    name: str
    mission: str
    department_owner: str


@dataclass(frozen=True)
class AgentCapability:
    capability_id: str
    name: str
    description: str
    required_skill_ids: tuple[str, ...]


@dataclass(frozen=True)
class AgentBoundary:
    allowed_inputs: tuple[str, ...]
    allowed_outputs: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    approval_required_actions: tuple[str, ...]


@dataclass(frozen=True)
class AgentRunMode:
    default: str
    network_allowed: bool
    external_action_allowed: bool
    persistence_allowed: bool


@dataclass(frozen=True)
class AgentSessionProfile:
    max_steps: int
    timeout_seconds: int
    checkpoint_required: bool
    human_interrupts: tuple[str, ...]


@dataclass(frozen=True)
class AgentHandoffRule:
    target_agent_id: str
    trigger: str
    payload_contract: str
    approval_required: bool


@dataclass(frozen=True)
class AgentEvaluationPolicy:
    trace_required: bool
    eval_required: bool
    metrics: tuple[str, ...]
    dataset_id: str


@dataclass(frozen=True)
class AgentDefinition:
    agent_id: str
    name: str
    department_owner: str
    role: str
    responsibilities: tuple[str, ...]
    allowed_inputs: tuple[str, ...]
    allowed_outputs: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    approval_required_actions: tuple[str, ...]
    model_tier: str
    budget_cap: float
    trace_required: bool
    eval_required: bool
    handoff_targets: tuple[str, ...]
    default_run_mode: str
    session_profile: AgentSessionProfile
    evaluation_policy: AgentEvaluationPolicy


@dataclass(frozen=True)
class AgentRegistryReport:
    report_version: str
    generated_at: str
    roles: tuple[AgentRole, ...]
    capabilities: tuple[AgentCapability, ...]
    agents: tuple[AgentDefinition, ...]
    handoff_rules: tuple[AgentHandoffRule, ...]
    boundary_policy: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_MANAGERS = (("ceo-orchestrator", "CEO Orchestrator", "management"), ("chief-of-staff", "Chief of Staff", "management"), ("management-manager", "Management Manager", "management"), ("finance-manager", "Finance Manager", "finance"), ("accounting-manager", "Accounting Manager", "accounting"), ("sales-manager", "Sales Manager", "sales"), ("risk-approval-manager", "Risk Approval Manager", "risk_approval"), ("intelligence-manager", "Intelligence Manager", "intelligence"), ("supplier-manager", "Supplier Manager", "supplier"), ("launch-manager", "Launch Manager", "launch"), ("site-builder-manager", "Site Builder Manager", "website_store_funnel"), ("operations-manager", "Operations Manager", "operations"))
_SPECIALISTS = (("budget-analyst", "Budget Analyst", "finance"), ("runway-forecaster", "Runway Forecaster", "finance"), ("spend-cap-controller", "Spend Cap Controller", "finance"), ("ledger-categorizer", "Ledger Categorizer", "accounting"), ("reconciliation-reviewer", "Reconciliation Reviewer", "accounting"), ("lead-researcher", "Lead Researcher", "sales"), ("lead-scoring-agent", "Lead Scoring Agent", "sales"), ("sdr-draft-agent", "SDR Draft Agent", "sales"), ("objection-handler", "Objection Handler", "sales"), ("proposal-builder", "Proposal Builder", "sales"), ("appointment-reminder-draft-agent", "Appointment Reminder Draft Agent", "sales"), ("approval-gatekeeper", "Approval Gatekeeper", "risk_approval"), ("risk-auditor", "Risk Auditor", "risk_approval"), ("model-cost-controller", "Model Cost Controller", "finance"), ("trace-reviewer", "Trace Reviewer", "management"), ("knowledge-librarian", "Knowledge Librarian", "intelligence"), ("tool-steward", "Tool Steward", "operations"), ("skill-curator", "Skill Curator", "operations"), ("workflow-designer", "Workflow Designer", "operations"))


def _agent(item: tuple[str, str, str], manager: bool) -> AgentDefinition:
    agent_id, name, department = item
    external = ("send_message", "send_email", "send_whatsapp", "send_sms", "place_call", "create_payment", "create_order", "publish", "launch_ad", "mutate_provider")
    mode = "approval_required" if manager and department in {"sales", "launch", "website_store_funnel"} else "read_only" if manager else "draft_only"
    tier = "human_review" if department == "risk_approval" else "cheap_api" if department == "sales" else "local_low_cost"
    return AgentDefinition(agent_id, name, department, "manager" if manager else "specialist", (f"Coordinate {department} work.", "Produce bounded operating artifacts."), ("approved context", "sanitized reports", "manual operator input"), ("draft report", "scorecard", "handoff", "approval request"), ("read_file", "query_vector_memory"), external, ("spend", "publish", "message", "payment", "order"), tier, 2.0 if not manager else 5.0, True, True, ("chief-of-staff", "approval-gatekeeper") if manager else ("manager-" + department,), mode, AgentSessionProfile(12, 120, True, ("pause_before_external_action", "pause_before_spend", "pause_before_message_send")), AgentEvaluationPolicy(True, True, ("groundedness", "schema_validity", "safety_boundary_respected", "no_live_action", "no_secret_leakage"), "companyos-registry-safety-v1"))


def build_agent_registry(*, generated_at: str = "offline-deterministic", seed: Mapping[str, Any] | None = None) -> AgentRegistryReport:
    agents = [_agent(item, True) for item in _MANAGERS] + [_agent(item, False) for item in _SPECIALISTS]
    overrides = {str(item.get("agent_id")): item for item in (seed or {}).get("agents", []) if isinstance(item, Mapping)}
    normalized: list[AgentDefinition] = []
    for agent in agents:
        override = overrides.get(agent.agent_id, {})
        mode = str(override.get("default_run_mode", agent.default_run_mode))
        if mode not in RUN_MODES:
            mode = "blocked"
        normalized.append(replace(agent, default_run_mode=mode))
    roles = tuple(AgentRole(item[0], item[1], f"Own bounded {item[2]} planning and review.", item[2]) for item in _MANAGERS + _SPECIALISTS)
    capabilities = tuple(AgentCapability(f"cap-{agent.agent_id}", f"{agent.name} planning", f"Create a deterministic {agent.name} artifact.", ()) for agent in normalized)
    handoffs = tuple(AgentHandoffRule(agent.agent_id, "approval or structured handoff is ready", target, True) for agent in normalized for target in agent.handoff_targets)
    return AgentRegistryReport("companyos-agent-registry-v1", generated_at, roles, capabilities, tuple(normalized), handoffs, "Agents may plan, summarize, score, and request approval; they may not act in the external world by default.")


__all__ = ["RUN_MODES", "AgentDefinition", "AgentRole", "AgentCapability", "AgentBoundary", "AgentRunMode", "AgentSessionProfile", "AgentHandoffRule", "AgentEvaluationPolicy", "AgentRegistryReport", "build_agent_registry"]
