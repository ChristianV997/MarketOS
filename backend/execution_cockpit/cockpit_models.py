from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

ACTION_TYPES = {"run_workflow", "resume_workflow", "replay_workflow_stage", "generate_optimization", "create_operating_plan", "update_task_status", "create_progress_review", "run_executive_intelligence", "generate_deliverable", "run_validation_sprint", "refresh_pipeline", "run_refinement", "run_source_calibration", "advisory_manual", "blocked"}
ACTION_STATUSES = {"proposed", "pending_approval", "approved", "rejected", "running", "completed", "blocked", "failed", "skipped"}
APPROVAL_DECISIONS = {"pending", "approved", "rejected"}
EXECUTION_STATUSES = {"created", "running", "completed", "blocked", "failed", "partial"}
CHECKPOINT_TYPES = {"before_execution", "after_execution", "failure", "blocked", "approval", "final"}


def _status(value: Any, allowed: set[str], fallback: str) -> str:
    return str(value) if str(value) in allowed else fallback


@dataclass
class CockpitAction:
    action_id: str
    workspace_id: str
    action_type: str
    title: str
    description: str
    source_task_id: str = ""
    source_packet_id: str = ""
    source_plan_id: str = ""
    safe_endpoint: str = ""
    safe_payload: dict[str, Any] = field(default_factory=dict)
    approval_required: bool = True
    approval_policy_id: str = "local_operator_approval"
    status: str = "proposed"
    blocked_reasons: list[str] = field(default_factory=list)
    safety_notes: list[str] = field(default_factory=lambda: ["Local internal action only; no external business action."])
    expected_outputs: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.action_type not in ACTION_TYPES:
            self.action_type = "blocked"
            self.blocked_reasons.append("unknown_action_type")
        self.status = _status(self.status, ACTION_STATUSES, "blocked")
        if self.blocked_reasons:
            self.status = "blocked"

    def to_dict(self): return {key: getattr(self, key) for key in self.__dataclass_fields__}
    @classmethod
    def from_dict(cls, data): return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})
    def to_markdown(self):
        return f"# {self.title}\n\n**Status:** `{self.status}`  \n**Action:** `{self.action_type}`  \n**Approval required:** `{self.approval_required}`\n\n{self.description}\n\n## Safe endpoint reference\n\n`{self.safe_endpoint or 'manual/advisory only'}`\n\n## Blockers\n\n" + "\n".join(f"- {x}" for x in self.blocked_reasons) + "\n\n## Safety\n\n" + "\n".join(f"- {x}" for x in self.safety_notes) + "\n\nNo live external action is executed by this cockpit.\n"


@dataclass
class CockpitApproval:
    approval_id: str
    workspace_id: str
    action_id: str
    decision: str = "pending"
    approver: str = "operator"
    reason: str = ""
    created_at: float = field(default_factory=time.time)
    decided_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    def __post_init__(self): self.decision = _status(self.decision, APPROVAL_DECISIONS, "pending")
    def to_dict(self): return {key: getattr(self, key) for key in self.__dataclass_fields__}
    @classmethod
    def from_dict(cls, data): return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})


@dataclass
class CockpitExecution:
    execution_id: str
    workspace_id: str
    action_id: str
    source_task_id: str = ""
    status: str = "created"
    started_at: float | None = None
    finished_at: float | None = None
    input_summary: dict[str, Any] = field(default_factory=dict)
    output_summary: dict[str, Any] = field(default_factory=dict)
    produced_object_ids: list[dict[str, Any]] = field(default_factory=list)
    checkpoint_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    blocked_reasons: list[str] = field(default_factory=list)
    safety_flags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    def __post_init__(self): self.status = _status(self.status, EXECUTION_STATUSES, "failed")
    def to_dict(self): return {key: getattr(self, key) for key in self.__dataclass_fields__}
    @classmethod
    def from_dict(cls, data): return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})


@dataclass
class CockpitCheckpoint:
    checkpoint_id: str
    workspace_id: str
    execution_id: str
    action_id: str
    checkpoint_type: str
    state_summary: dict[str, Any] = field(default_factory=dict)
    produced_object_ids: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
    def __post_init__(self): self.checkpoint_type = _status(self.checkpoint_type, CHECKPOINT_TYPES, "blocked")
    def to_dict(self): return {key: getattr(self, key) for key in self.__dataclass_fields__}
    @classmethod
    def from_dict(cls, data): return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})


@dataclass
class CockpitRunSummary:
    summary_id: str
    workspace_id: str
    plan_id: str
    execution_ids: list[str] = field(default_factory=list)
    completed_count: int = 0
    blocked_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    produced_outputs: list[dict[str, Any]] = field(default_factory=list)
    progress_snapshot_id: str = ""
    next_actions: list[str] = field(default_factory=list)
    safety_notes: list[str] = field(default_factory=lambda: ["Cockpit execution is limited to approved internal local actions."])
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
    def to_dict(self): return {key: getattr(self, key) for key in self.__dataclass_fields__}
    @classmethod
    def from_dict(cls, data): return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})
    def to_markdown(self):
        return f"# Cockpit Run Summary\n\n**Plan:** `{self.plan_id}`  \n**Completed:** `{self.completed_count}`  \n**Blocked:** `{self.blocked_count}`  \n**Failed:** `{self.failed_count}`  \n**Skipped:** `{self.skipped_count}`\n\n## Next actions\n\n" + "\n".join(f"- {x}" for x in self.next_actions) + "\n\n## Safety\n\n" + "\n".join(f"- {x}" for x in self.safety_notes) + "\n"
