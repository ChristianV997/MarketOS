from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

TASK_TYPES = {"evidence_import", "evidence_acquisition", "discovery", "refinement", "acquisition_planning", "pipeline_refresh", "source_calibration", "validation_sprint", "deliverable_generation", "executive_review", "portfolio_optimization", "risk_resolution", "manual_review", "documentation"}
TASK_STATUSES = {"proposed", "planned", "ready", "blocked", "in_progress", "completed", "skipped", "cancelled", "carried_over"}
HORIZONS = {"daily", "weekly", "sprint", "monthly"}
PLAN_STATUSES = {"drafted", "active", "completed", "partial", "blocked", "archived"}


def _num(value: Any, low: float = 0.0, high: float = 100.0) -> float:
    try:
        return max(low, min(float(value), high))
    except (TypeError, ValueError):
        return low


def _safe_status(value: Any, allowed: set[str], fallback: str) -> str:
    return str(value) if str(value) in allowed else fallback


@dataclass
class OperatingTask:
    task_id: str
    workspace_id: str
    title: str
    description: str
    task_type: str = "manual_review"
    status: str = "proposed"
    priority_score: float = 0.0
    simulated_cost: float = 0.0
    estimated_hours: float = 0.0
    due_day: str = "backlog"
    sequence_order: int = 0
    depends_on_task_ids: list[str] = field(default_factory=list)
    blocks_task_ids: list[str] = field(default_factory=list)
    related_action_id: str = ""
    related_opportunity_ids: list[str] = field(default_factory=list)
    related_gap_ids: list[str] = field(default_factory=list)
    related_acquisition_plan_ids: list[str] = field(default_factory=list)
    related_workflow_ids: list[str] = field(default_factory=list)
    related_deliverable_ids: list[str] = field(default_factory=list)
    safe_endpoint: str = ""
    safe_payload: dict[str, Any] = field(default_factory=dict)
    expected_outputs: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    checklist: list[str] = field(default_factory=list)
    blocker_reasons: list[str] = field(default_factory=list)
    safety_notes: list[str] = field(default_factory=lambda: ["Planning-only task; never execute automatically."])
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.task_type not in TASK_TYPES:
            self.task_type = "manual_review"
        self.status = _safe_status(self.status, TASK_STATUSES, "blocked")
        self.priority_score = _num(self.priority_score)
        self.simulated_cost = _num(self.simulated_cost, 0, 1_000_000)
        self.estimated_hours = _num(self.estimated_hours, 0, 10_000)
        self.checklist = list(self.checklist or ["Review inputs and provenance", "Complete the safe/manual step", "Record produced artifacts and blockers"])
        self.acceptance_criteria = list(self.acceptance_criteria or ["Output is recorded in a local registry or operator note."])

    def to_dict(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OperatingTask":
        return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})

    def to_markdown(self) -> str:
        return f"## {self.title}\n\n- **Status:** `{self.status}`\n- **Type:** `{self.task_type}`\n- **Priority:** `{self.priority_score:.1f}`\n- **Day:** `{self.due_day}`\n- **Estimate:** `{self.estimated_hours:.1f}h`, simulated `${self.simulated_cost:.2f}`\n- **Depends on:** {', '.join(self.depends_on_task_ids) or 'none'}\n\n### Checklist\n" + "\n".join(f"- [ ] {item}" for item in self.checklist) + "\n\n### Safety\n\n" + "\n".join(f"- {item}" for item in self.safety_notes)


@dataclass
class OperatingPlan:
    plan_id: str
    workspace_id: str
    title: str
    objective: str
    horizon: str = "weekly"
    source_optimization_id: str = ""
    source_action_set_id: str = ""
    status: str = "drafted"
    tasks: list[OperatingTask] = field(default_factory=list)
    day_plan: dict[str, list[str]] = field(default_factory=dict)
    blocked_task_ids: list[str] = field(default_factory=list)
    critical_path_task_ids: list[str] = field(default_factory=list)
    estimated_total_hours: float = 0.0
    simulated_total_cost: float = 0.0
    expected_outputs: list[str] = field(default_factory=list)
    review_cadence_id: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.horizon not in HORIZONS:
            self.horizon = "weekly"
        self.status = _safe_status(self.status, PLAN_STATUSES, "blocked")
        self.estimated_total_hours = _num(self.estimated_total_hours, 0, 100_000)
        self.simulated_total_cost = _num(self.simulated_total_cost, 0, 1_000_000_000)

    def to_dict(self) -> dict[str, Any]:
        return {key: ([item.to_dict() for item in value] if key == "tasks" else value) for key, value in ((key, getattr(self, key)) for key in self.__dataclass_fields__)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OperatingPlan":
        data = dict(data)
        data["tasks"] = [OperatingTask.from_dict(item) for item in data.get("tasks", [])]
        return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})

    def to_markdown(self) -> str:
        tasks = "\n\n".join(task.to_markdown() for task in self.tasks) or "No tasks proposed."
        return f"# {self.title}\n\n**Objective:** {self.objective}\n\n**Horizon:** `{self.horizon}`  \n**Status:** `{self.status}`  \n**Estimate:** `{self.estimated_total_hours:.1f}h`, simulated `${self.simulated_total_cost:.2f}`\n\n## Day plan\n\n" + "\n".join(f"- **{day}:** {', '.join(ids) or 'none'}" for day, ids in self.day_plan.items()) + f"\n\n## Tasks\n\n{tasks}\n\n> No task is automatically executed. Calendar and cost values are planning assumptions only.\n"


@dataclass
class TaskPacket:
    packet_id: str
    workspace_id: str
    plan_id: str
    task_id: str
    title: str
    objective: str
    instructions: list[str] = field(default_factory=list)
    input_requirements: list[str] = field(default_factory=list)
    expected_artifacts: list[str] = field(default_factory=list)
    exact_commands_or_endpoints: list[dict[str, Any]] = field(default_factory=list)
    checklist: list[str] = field(default_factory=list)
    done_definition: list[str] = field(default_factory=list)
    safety_constraints: list[str] = field(default_factory=lambda: ["Do not execute automatically.", "Do not call external systems or spend money."])
    troubleshooting: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskPacket":
        return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})

    def to_markdown(self) -> str:
        bullets = lambda values: "\n".join(f"- {value}" for value in values) or "- None."
        return f"# {self.title}\n\n{self.objective}\n\n## Instructions\n\n{bullets(self.instructions)}\n\n## Inputs\n\n{bullets(self.input_requirements)}\n\n## Checklist\n\n{bullets(self.checklist)}\n\n## Done definition\n\n{bullets(self.done_definition)}\n\n## Safety constraints\n\n{bullets(self.safety_constraints)}\n"
