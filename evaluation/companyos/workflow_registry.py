"""Durable-workflow-shaped definitions without a workflow runner."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class WorkflowTrigger:
    trigger_type: str
    description: str
    operator_confirmation_required: bool


@dataclass(frozen=True)
class WorkflowStep:
    step_id: str
    name: str
    action_type: str
    input_contract: str
    output_contract: str
    checkpoint_after: bool
    interrupt_before: str | None


@dataclass(frozen=True)
class WorkflowCheckpoint:
    checkpoint_id: str
    after_step: str
    persisted_fields: tuple[str, ...]
    resume_policy: str


@dataclass(frozen=True)
class WorkflowInterrupt:
    interrupt_id: str
    point: str
    reason: str
    approver_role: str
    resume_condition: str


@dataclass(frozen=True)
class WorkflowRetryPolicy:
    max_attempts: int
    backoff: str
    retryable_failures: tuple[str, ...]


@dataclass(frozen=True)
class WorkflowFailurePolicy:
    failure_mode: str
    notify_role: str
    preserve_checkpoint: bool
    next_action: str


@dataclass(frozen=True)
class WorkflowApprovalStep:
    step_id: str
    approval_type: str
    required: bool
    forbidden_without_approval: tuple[str, ...]


@dataclass(frozen=True)
class WorkflowRunEnvelope:
    workflow_id: str
    run_id_format: str
    correlation_id_required: bool
    advisory: bool
    authoritative: bool


@dataclass(frozen=True)
class WorkflowOutputContract:
    schema_version: str
    output_type: str
    human_review_required: bool


@dataclass(frozen=True)
class WorkflowDefinition:
    workflow_id: str
    name: str
    department_owner: str
    trigger: WorkflowTrigger
    steps: tuple[WorkflowStep, ...]
    human_approval_points: tuple[WorkflowInterrupt, ...]
    allowed_tools: tuple[str, ...]
    forbidden_tools: tuple[str, ...]
    checkpoint_policy: tuple[WorkflowCheckpoint, ...]
    retry_policy: WorkflowRetryPolicy
    failure_policy: WorkflowFailurePolicy
    audit_event_type: str
    output_contract: WorkflowOutputContract
    approval_steps: tuple[WorkflowApprovalStep, ...]
    run_envelope: WorkflowRunEnvelope


@dataclass(frozen=True)
class WorkflowRegistryReport:
    report_version: str
    generated_at: str
    workflows: tuple[WorkflowDefinition, ...]
    global_interrupts: tuple[str, ...]
    policy: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_WORKFLOWS = (("weekly_operating_review", "weekly operating review", "management"), ("product_opportunity_to_launch_pack", "product opportunity to launch pack", "launch"), ("launch_pack_to_site_draft", "launch pack to site draft", "website_store_funnel"), ("lead_to_sales_brief", "lead to sales brief", "sales"), ("sales_brief_to_proposal", "sales brief to proposal", "sales"), ("finance_budget_review", "finance budget review", "finance"), ("accounting_period_close", "accounting period close", "accounting"), ("approval_queue_review", "approval queue review", "risk_approval"), ("supplier_proof_review", "supplier proof review", "supplier"), ("model_cost_review", "model cost review", "finance"))


def _workflow(item: tuple[str, str, str]) -> WorkflowDefinition:
    workflow_id, name, department = item
    steps = (WorkflowStep("collect", "Collect sanitized context", "read_only", "approved_context", "normalized_context", True, None), WorkflowStep("review", "Review structured result", "draft", "normalized_context", "draft_decision", True, "pause_before_external_action"), WorkflowStep("handoff", "Prepare human handoff", "draft", "draft_decision", "handoff_packet", True, "pause_before_message_send"))
    interrupts = tuple(WorkflowInterrupt(f"{workflow_id}-{point}", point, f"Stop before {point.replace('_', ' ')}.", "management", "explicit approval record") for point in ("pause_before_external_action", "pause_before_spend", "pause_before_message_send", "pause_before_publish", "pause_before_payment", "pause_before_order"))
    return WorkflowDefinition(workflow_id, name, department, WorkflowTrigger("manual_or_approved_event", "Operator starts an offline draft workflow.", True), steps, interrupts, ("read_file", "run_script"), ("send_email", "send_whatsapp", "send_sms", "place_call", "create_payment", "create_order", "publish_site", "launch_ad", "sync_accounting"), tuple(WorkflowCheckpoint(f"{workflow_id}-{step.step_id}", step.step_id, ("run_id", "step_output", "warnings"), "resume_after_review") for step in steps if step.checkpoint_after), WorkflowRetryPolicy(1, "none", ("malformed_input",)), WorkflowFailurePolicy("stop_and_preserve", "management", True, "review failure and correct input manually"), f"companyos_workflow_{workflow_id}", WorkflowOutputContract("companyos-workflow-v1", "advisory_handoff", True), tuple(WorkflowApprovalStep(step.step_id, "human_review", True, ("external action", "spend", "message", "publish")) for step in steps), WorkflowRunEnvelope(workflow_id, f"{workflow_id}-<uuid>", True, True, False))


def build_workflow_registry(*, generated_at: str = "offline-deterministic", seed: Mapping[str, Any] | None = None) -> WorkflowRegistryReport:
    workflows = tuple(_workflow(item) for item in _WORKFLOWS)
    return WorkflowRegistryReport("companyos-workflow-registry-v1", generated_at, workflows, ("pause_before_external_action", "pause_before_spend", "pause_before_message_send", "pause_before_publish", "pause_before_payment", "pause_before_order"), "Definitions model checkpoints, retries, failures, and interrupts; no workflow runner is installed.")


__all__ = ["WorkflowDefinition", "WorkflowStep", "WorkflowTrigger", "WorkflowCheckpoint", "WorkflowInterrupt", "WorkflowRetryPolicy", "WorkflowFailurePolicy", "WorkflowApprovalStep", "WorkflowRunEnvelope", "WorkflowOutputContract", "WorkflowRegistryReport", "build_workflow_registry"]
