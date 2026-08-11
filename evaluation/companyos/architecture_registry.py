"""Curated architecture references and integration decisions for CompanyOS.

This is a decision record, not a dependency manifest. External projects are
not installed, imported, called, or copied into runtime execution.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

INTEGRATION_MODES = frozenset({"integrate_now", "integrate_soon", "emulate_now", "study_later", "avoid_for_now"})


@dataclass(frozen=True)
class ExternalSystemReference:
    system_id: str
    name: str
    category: str
    license_model: str
    commercial_use_note: str
    integration_mode: str
    capability_gain: str
    development_time_saved: str
    cost_risk: str
    license_risk: str
    security_risk: str
    operational_complexity: str
    recommended_marketos_mapping: str
    integrate_now_reason: str
    emulate_now_reason: str
    avoid_now_reason: str
    next_review_trigger: str


@dataclass(frozen=True)
class CostBenefitAssessment:
    system_id: str
    benefit_score: float
    cost_score: float
    net_value: float
    assumptions: tuple[str, ...]


@dataclass(frozen=True)
class LicenseRiskAssessment:
    system_id: str
    license_model: str
    commercial_use_status: str
    review_required: bool
    notes: tuple[str, ...]


@dataclass(frozen=True)
class SecurityRiskAssessment:
    system_id: str
    risk_level: str
    data_boundary: str
    controls: tuple[str, ...]
    review_required: bool


@dataclass(frozen=True)
class IntegrationCandidate:
    system_id: str
    capability: str
    candidate_use: str
    prerequisites: tuple[str, ...]
    blocked_until: tuple[str, ...]


@dataclass(frozen=True)
class IntegrationDecision:
    system_id: str
    decision: str
    priority: str
    rationale: str
    owner_department: str
    next_review_trigger: str


@dataclass(frozen=True)
class ArchitecturePattern:
    pattern_id: str
    name: str
    references: tuple[str, ...]
    marketos_emulation: str
    safety_boundary: str


@dataclass(frozen=True)
class ImplementationPriority:
    item_id: str
    priority: str
    score: float
    dependency_gate: str
    next_action: str


@dataclass(frozen=True)
class ArchitectureRegistryReport:
    report_version: str
    generated_at: str
    references: tuple[ExternalSystemReference, ...]
    candidates: tuple[IntegrationCandidate, ...]
    decisions: tuple[IntegrationDecision, ...]
    cost_benefit: tuple[CostBenefitAssessment, ...]
    license_risks: tuple[LicenseRiskAssessment, ...]
    security_risks: tuple[SecurityRiskAssessment, ...]
    patterns: tuple[ArchitecturePattern, ...]
    priorities: tuple[ImplementationPriority, ...]
    default_policy: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _ref(system_id: str, name: str, category: str, mode: str, mapping: str, license_model: str = "review_required", security: str = "medium") -> ExternalSystemReference:
    return ExternalSystemReference(system_id, name, category, license_model, "Commercial use requires license and hosted-data review.", mode, f"Reference capability: {category}.", "Potentially reduces bespoke design work.", "managed dependency and usage cost", "license terms and distribution obligations", security, "medium", mapping, "No integration in registry-only phase.", f"Emulate {category} concepts in deterministic schemas first.", "Avoid credentials, live actions, and operational dependency until an approved gate exists.", "When a concrete workload, owner, budget, and security review are approved.")


def default_references() -> list[ExternalSystemReference]:
    specs = [
        ("onyx", "Onyx", "company brain / RAG", "emulate_now", "knowledge_registry and citation policy"), ("dify", "Dify", "LLM apps / workflows", "emulate_now", "skill and workflow contracts"), ("langgraph", "LangGraph", "durable graph workflows", "emulate_now", "workflow checkpoints and interrupts"), ("autogen", "AutoGen", "multi-agent conversations", "study_later", "agent handoff rules"), ("crewai", "CrewAI", "role-based agents", "study_later", "agent role registry"), ("openhands", "OpenHands", "agent sessions / sandbox", "study_later", "agent session profile"), ("herdr", "Herdr", "agent session operations", "study_later", "run envelope and sandbox policy"), ("hermes-skills-hub", "Hermes Skills Hub", "skills catalog", "emulate_now", "curated skill registry"), ("ecc", "ECC", "engineering context / skills", "emulate_now", "skill boundary and test cases"), ("agency-agents", "Agency-agents", "personas and procedures", "emulate_now", "role and procedure templates"), ("litellm", "LiteLLM", "model gateway / budgets", "integrate_soon", "model router and cost controller"), ("langfuse", "Langfuse", "tracing / prompts / evals", "integrate_soon", "trace and eval registry"), ("phoenix", "Phoenix", "observability / evals", "study_later", "quality gate and trace policy"), ("activepieces", "Activepieces", "integration workflows", "emulate_now", "tool registry and approval policy"), ("n8n", "n8n", "workflow automation", "emulate_now", "workflow and tool contracts"), ("windmill", "Windmill", "script workflows", "emulate_now", "run_script tool boundary"), ("pipedream", "Pipedream", "managed integrations", "study_later", "provider candidate metadata"), ("composio", "Composio", "tool integrations", "emulate_now", "tool catalog and side-effect profile"), ("inngest", "Inngest", "durable functions", "emulate_now", "retry and checkpoint policy"), ("trigger-dev", "Trigger.dev", "background workflows", "emulate_now", "workflow run envelope"), ("temporal", "Temporal", "durable orchestration", "study_later", "workflow failure policy"), ("llamaindex", "LlamaIndex", "RAG orchestration", "emulate_now", "knowledge retrieval profile"), ("haystack", "Haystack", "retrieval pipelines", "emulate_now", "retrieval and citation policy"), ("supabase-pgvector", "Supabase pgvector", "memory / vector storage", "study_later", "knowledge source registry"), ("vllm", "vLLM", "self-hosted inference", "study_later", "model provider candidate"), ("ollama", "Ollama", "local inference", "emulate_now", "local model tier"), ("llama-cpp", "llama.cpp", "embedded local inference", "study_later", "local model tier"), ("aws-bedrock-agentcore", "AWS Bedrock / AgentCore", "managed model / agent runtime", "study_later", "provider candidate and approval boundary"),
    ]
    return [_ref(*item) for item in specs]


def build_architecture_registry(*, generated_at: str = "offline-deterministic", seed: Mapping[str, Any] | None = None) -> ArchitectureRegistryReport:
    references = default_references()
    overrides = {str(item.get("system_id")): item for item in (seed or {}).get("references", []) if isinstance(item, Mapping)}
    references = [ExternalSystemReference(**{**asdict(item), "integration_mode": str(overrides.get(item.system_id, {}).get("integration_mode", item.integration_mode))}) for item in references]
    candidates = tuple(IntegrationCandidate(item.system_id, item.category, item.recommended_marketos_mapping, ("owner and budget", "security review", "explicit approval"), ("registry review", "no credentials by default")) for item in references)
    priority_map = {"litellm": ("high", 9.0), "langfuse": ("high", 8.5), "langgraph": ("medium", 7.5), "onyx": ("medium", 7.0), "supabase-pgvector": ("low", 5.0)}
    decisions = tuple(IntegrationDecision(item.system_id, item.integration_mode, priority_map.get(item.system_id, ("low", 4.0))[0], "Emulate schema first; no external integration in this PR.", "management", item.next_review_trigger) for item in references)
    cost = tuple(CostBenefitAssessment(item.system_id, 8.0 if item.system_id in priority_map else 5.0, 7.0 if item.integration_mode in {"integrate_soon", "study_later"} else 3.0, round((8.0 if item.system_id in priority_map else 5.0) - (7.0 if item.integration_mode in {"integrate_soon", "study_later"} else 3.0), 2), ("No dependency is added.", "Benefit is a planning estimate.")) for item in references)
    license_risks = tuple(LicenseRiskAssessment(item.system_id, item.license_model, "review_required", True, ("Confirm current upstream terms before adoption.",)) for item in references)
    security_risks = tuple(SecurityRiskAssessment(item.system_id, item.security_risk, "offline metadata only", ("no credentials", "least authority", "human approval", "audit trace"), True) for item in references)
    patterns = (ArchitecturePattern("company-brain", "Company brain", ("onyx", "llamaindex", "haystack", "supabase-pgvector"), "knowledge sources, retrieval profiles, citations", "No indexing or retrieval calls."), ArchitecturePattern("durable-workflow", "Durable workflow", ("langgraph", "inngest", "trigger-dev", "temporal"), "steps, checkpoints, retries, interrupts", "No runner or external side effect."), ArchitecturePattern("model-gateway", "Model gateway", ("litellm", "ollama", "vllm", "aws-bedrock-agentcore"), "model tiers, budgets, fallback policy", "No model calls or credentials."), ArchitecturePattern("trace-eval", "Trace and evaluation", ("langfuse", "phoenix"), "trace specs, datasets, quality gates", "No telemetry export."), ArchitecturePattern("tool-catalog", "Tool catalog", ("composio", "pipedream", "activepieces", "n8n", "windmill"), "risk levels, schemas, approval policy", "Real-world tools blocked or approval-gated."))
    priorities = tuple(ImplementationPriority(item, priority, score, "approved workload and security review", f"Define a bounded adapter only after the trigger: {item}.") for item, (priority, score) in priority_map.items())
    return ArchitectureRegistryReport("companyos-architecture-registry-v1", generated_at, tuple(references), candidates, decisions, cost, license_risks, security_risks, patterns, priorities, "Do not integrate external systems in this registry-only PR; emulate contracts first.")


__all__ = ["INTEGRATION_MODES", "ExternalSystemReference", "IntegrationCandidate", "IntegrationDecision", "ArchitecturePattern", "CostBenefitAssessment", "LicenseRiskAssessment", "SecurityRiskAssessment", "ImplementationPriority", "ArchitectureRegistryReport", "default_references", "build_architecture_registry"]
