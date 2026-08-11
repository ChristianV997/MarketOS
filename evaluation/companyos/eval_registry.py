"""Trace and evaluation policy registry inspired by observability platforms."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

METRICS = ("groundedness", "citation_required", "schema_validity", "safety_boundary_respected", "no_live_action", "cost_within_budget", "determinism", "approval_required_when_needed", "no_secret_leakage", "no_unapproved_claims")
QUALITY_GATES = ("companyos_registry_gate", "sales_draft_safety_gate", "finance_assumption_gate", "accounting_ledger_gate", "tool_risk_gate", "model_cost_gate", "approval_required_gate")


@dataclass(frozen=True)
class TracePolicy:
    policy_id: str
    capture_inputs: bool
    capture_outputs: bool
    redact_fields: tuple[str, ...]
    retention: str
    sampling: str


@dataclass(frozen=True)
class AgentTraceSpec:
    agent_id: str
    trace_policy_id: str
    required_spans: tuple[str, ...]
    correlation_fields: tuple[str, ...]


@dataclass(frozen=True)
class ModelCallTraceSpec:
    route_type: str
    required_fields: tuple[str, ...]
    cost_fields: tuple[str, ...]
    prompt_version_required: bool


@dataclass(frozen=True)
class ToolCallTraceSpec:
    tool_category: str
    required_fields: tuple[str, ...]
    approval_evidence_required: bool
    output_redaction_required: bool


@dataclass(frozen=True)
class PromptVersion:
    prompt_id: str
    version: str
    owner: str
    status: str
    change_note: str


@dataclass(frozen=True)
class EvaluationDataset:
    dataset_id: str
    name: str
    source: str
    privacy_classification: str
    case_count: int


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    dataset_id: str
    input_summary: str
    expected_properties: tuple[str, ...]


@dataclass(frozen=True)
class EvaluationMetric:
    metric_id: str
    name: str
    threshold: str
    failure_action: str


@dataclass(frozen=True)
class RegressionCheck:
    check_id: str
    metric_id: str
    baseline: str
    tolerance: str
    blocking: bool


@dataclass(frozen=True)
class QualityGate:
    gate_id: str
    name: str
    metric_ids: tuple[str, ...]
    applies_to: tuple[str, ...]
    blocking: bool
    failure_message: str


@dataclass(frozen=True)
class EvalRegistryReport:
    report_version: str
    generated_at: str
    trace_policies: tuple[TracePolicy, ...]
    agent_traces: tuple[AgentTraceSpec, ...]
    model_traces: tuple[ModelCallTraceSpec, ...]
    tool_traces: tuple[ToolCallTraceSpec, ...]
    prompt_versions: tuple[PromptVersion, ...]
    datasets: tuple[EvaluationDataset, ...]
    cases: tuple[EvaluationCase, ...]
    metrics: tuple[EvaluationMetric, ...]
    regressions: tuple[RegressionCheck, ...]
    quality_gates: tuple[QualityGate, ...]
    integration_mapping: dict[str, tuple[str, ...]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_eval_registry(*, generated_at: str = "offline-deterministic", seed: Mapping[str, Any] | None = None) -> EvalRegistryReport:
    policy = TracePolicy("companyos-default-trace", False, True, ("password", "token", "api_key", "authorization", "private_data"), "repository-policy", "deterministic")
    metrics = tuple(EvaluationMetric(metric, metric.replace("_", " "), "required", "block and review") for metric in METRICS)
    metric_ids = tuple(item.metric_id for item in metrics)
    gates = tuple(QualityGate(gate, gate.replace("_", " "), metric_ids, ("agent", "skill", "tool", "workflow", "model"), True, "Registry quality or safety requirement failed.") for gate in QUALITY_GATES)
    return EvalRegistryReport("companyos-eval-registry-v1", generated_at, (policy,), (AgentTraceSpec("all_registered_agents", policy.policy_id, ("agent_start", "decision", "handoff", "agent_end"), ("run_id", "department", "approval_id")),), (ModelCallTraceSpec("all_registered_routes", ("run_id", "route", "model", "latency"), ("estimated_cost", "budget_remaining"), True),), (ToolCallTraceSpec("all_registered_tools", ("run_id", "tool_id", "risk_level"), True, True),), (PromptVersion("companyos-registry-prompts", "1.0.0", "MarketOS", "verified", "Initial registry policy"),), (EvaluationDataset("companyos-registry-safety-v1", "CompanyOS registry safety cases", "synthetic repository fixtures", "synthetic", 1),), (EvaluationCase("registry-safe-defaults", "companyos-registry-safety-v1", "All registries in offline mode", metric_ids),), metrics, tuple(RegressionCheck(f"regression-{metric}", metric, "pass", "no regression", True) for metric in metric_ids), gates, {"Langfuse": ("trace collection", "prompt/version management", "eval datasets", "cost monitoring"), "Phoenix": ("trace collection", "regression testing", "quality monitoring"), "local CI": ("determinism", "schema validity", "secret leakage")})


__all__ = ["METRICS", "QUALITY_GATES", "TracePolicy", "AgentTraceSpec", "ModelCallTraceSpec", "ToolCallTraceSpec", "PromptVersion", "EvaluationDataset", "EvaluationCase", "EvaluationMetric", "RegressionCheck", "QualityGate", "EvalRegistryReport", "build_eval_registry"]
