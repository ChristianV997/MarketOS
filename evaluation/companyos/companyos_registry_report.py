"""Combined CompanyOS registry report."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .agent_registry import AgentRegistryReport, build_agent_registry
from .architecture_registry import ArchitectureRegistryReport, build_architecture_registry
from .eval_registry import EvalRegistryReport, build_eval_registry
from .knowledge_registry import KnowledgeRegistryReport, build_knowledge_registry
from .model_router import ModelRouterReport, build_model_router
from .skill_registry import SkillRegistryReport, build_skill_registry
from .tool_registry import ToolRegistryReport, build_tool_registry
from .workflow_registry import WorkflowRegistryReport, build_workflow_registry


@dataclass(frozen=True)
class CompanyOSRegistryReport:
    report_version: str
    generated_at: str
    architecture: ArchitectureRegistryReport
    agents: AgentRegistryReport
    skills: SkillRegistryReport
    tools: ToolRegistryReport
    workflows: WorkflowRegistryReport
    model_router: ModelRouterReport
    eval_registry: EvalRegistryReport
    knowledge: KnowledgeRegistryReport
    registry_count: int
    agent_count: int
    skill_count: int
    tool_count: int
    workflow_count: int
    model_route_count: int
    quality_gate_count: int
    knowledge_source_count: int
    integration_decisions: tuple[dict[str, Any], ...]
    highest_priority_next_integrations: tuple[str, ...]
    blocked_capabilities: tuple[str, ...]
    safety_summary: dict[str, Any]
    next_best_action: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_markdown(self) -> str:
        decisions = self.integration_decisions
        lines = ["# CompanyOS Agent / Skill / Tool / Workflow Registry", "", "## Summary", "", f"- Registries: **{self.registry_count}**", f"- Agents: **{self.agent_count}**", f"- Skills: **{self.skill_count}**", f"- Tools: **{self.tool_count}**", f"- Workflows: **{self.workflow_count}**", f"- Model routes: **{self.model_route_count}**", f"- Quality gates: **{self.quality_gate_count}**", f"- Knowledge sources: **{self.knowledge_source_count}**", "", "## Integration Roadmap", "", "| System | Decision | Priority |", "|---|---|---|"]
        lines.extend(f"| {item['system_id']} | {item['decision']} | {item['priority']} |" for item in decisions)
        lines += ["", "## Highest-Priority Next Integrations", ""]
        lines.extend(f"- {item}" for item in self.highest_priority_next_integrations)
        lines += ["", "## Blocked Capabilities", ""]
        lines.extend(f"- {item}" for item in self.blocked_capabilities)
        lines += ["", "## Safety Summary", "", "- Registry-only; no external systems are installed or called.", "- Real-world tools are blocked or approval-gated.", "- Agent messages, payments, publishing, orders, ads, and CRM/accounting mutations remain unavailable.", "", "## Next Best Action", "", self.next_best_action]
        return "\n".join(lines) + "\n"


def build_companyos_registry_report(*, generated_at: str = "offline-deterministic", seeds: Mapping[str, Mapping[str, Any]] | None = None) -> CompanyOSRegistryReport:
    seeds = seeds or {}
    architecture = build_architecture_registry(generated_at=generated_at, seed=seeds.get("architecture"))
    agents = build_agent_registry(generated_at=generated_at, seed=seeds.get("agents"))
    skills = build_skill_registry(generated_at=generated_at, seed=seeds.get("skills"))
    tools = build_tool_registry(generated_at=generated_at, seed=seeds.get("tools"))
    workflows = build_workflow_registry(generated_at=generated_at, seed=seeds.get("workflows"))
    model_router = build_model_router(generated_at=generated_at, seed=seeds.get("model_router"))
    eval_registry = build_eval_registry(generated_at=generated_at, seed=seeds.get("evals"))
    knowledge = build_knowledge_registry(generated_at=generated_at, seed=seeds.get("knowledge"))
    decisions = tuple(asdict(item) for item in architecture.decisions)
    priority = tuple(f"{item.item_id}: bounded {item.priority}-priority review before any integration" for item in architecture.priorities)
    return CompanyOSRegistryReport("companyos-registry-layer-v1", generated_at, architecture, agents, skills, tools, workflows, model_router, eval_registry, knowledge, 8, len(agents.agents), len(skills.skills), len(tools.tools), len(workflows.workflows), len(model_router.policy.routes), len(eval_registry.quality_gates), len(knowledge.sources), decisions, priority or ("No external integration; continue with local schemas and tests.",), ("send_email", "send_whatsapp", "send_sms", "place_call", "create_payment", "create_order", "launch_ad", "publish_site", "sync_accounting", "vector_indexing", "live_model_calls"), {"read_only": True, "network_calls": False, "model_calls": False, "external_actions": False, "credentials_present": False, "approval_required": True}, "Review LiteLLM/Langfuse as future bounded candidates only after a concrete workload, owner, budget, security review, and approval ledger gate exist.")


__all__ = ["CompanyOSRegistryReport", "build_companyos_registry_report"]
