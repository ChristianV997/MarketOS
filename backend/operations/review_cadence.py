from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReviewCheckpoint:
    checkpoint_id: str
    workspace_id: str
    plan_id: str
    checkpoint_type: str
    title: str
    questions: list[str] = field(default_factory=list)
    expected_inputs: list[str] = field(default_factory=list)
    expected_outputs: list[str] = field(default_factory=list)
    related_task_ids: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
    def to_dict(self): return {key: getattr(self, key) for key in self.__dataclass_fields__}
    @classmethod
    def from_dict(cls, data): return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})


@dataclass
class ProgressSnapshot:
    snapshot_id: str
    workspace_id: str
    plan_id: str
    completed_task_ids: list[str] = field(default_factory=list)
    blocked_task_ids: list[str] = field(default_factory=list)
    carried_over_task_ids: list[str] = field(default_factory=list)
    cancelled_task_ids: list[str] = field(default_factory=list)
    produced_outputs: list[dict[str, Any]] = field(default_factory=list)
    progress_summary: str = ""
    blockers: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
    def to_dict(self): return {key: getattr(self, key) for key in self.__dataclass_fields__}
    @classmethod
    def from_dict(cls, data): return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})
    def to_markdown(self): return f"# Progress Snapshot\n\n{self.progress_summary}\n\n## Blockers\n\n" + "\n".join(f"- {x}" for x in self.blockers) + "\n\n## Next actions\n\n" + "\n".join(f"- {x}" for x in self.next_actions)


@dataclass
class ReviewCadence:
    cadence_id: str
    workspace_id: str
    plan_id: str
    checkpoints: list[ReviewCheckpoint] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
    def to_dict(self): return {key: ([x.to_dict() for x in value] if key == "checkpoints" else value) for key, value in ((key, getattr(self, key)) for key in self.__dataclass_fields__)}
    @classmethod
    def from_dict(cls, data):
        data = dict(data); data["checkpoints"] = [ReviewCheckpoint.from_dict(x) for x in data.get("checkpoints", [])]
        return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})
    def to_markdown(self): return "# Review Cadence\n\n" + "\n\n".join(f"## {x.title}\n\n" + "\n".join(f"- {q}" for q in x.questions) for x in self.checkpoints)


QUESTIONS = ["What changed?", "What evidence arrived?", "Which tasks produced artifacts?", "Which blockers remain?", "Should priorities change?", "Should pipeline, refinement, or optimization rerun?", "Is an executive brief needed?"]


def build_review_cadence(plan):
    days = sorted(plan.day_plan)
    blocked_ids = list(plan.blocked_task_ids) or [x.task_id for x in plan.tasks if x.status == "blocked"]
    checkpoints = []
    for day in days:
        ids = plan.day_plan.get(day, [])
        if ids:
            for kind, title in (("daily_start", f"{day} start"), ("daily_end", f"{day} review")):
                checkpoints.append(ReviewCheckpoint(f"checkpoint_{plan.plan_id}_{kind}_{day}", plan.workspace_id, plan.plan_id, kind, title, QUESTIONS[:], ["Operating plan", "Task packets"], ["Progress note", "Produced artifact refs"], ids))
    if plan.horizon in {"weekly", "sprint", "monthly"}:
        checkpoints.append(ReviewCheckpoint(f"checkpoint_{plan.plan_id}_weekly_review", plan.workspace_id, plan.plan_id, "weekly_review", "Weekly operating review", QUESTIONS[:], ["Progress snapshots", "Blocked tasks"], ["Next-cycle adjustments"], [x.task_id for x in plan.tasks]))
    if blocked_ids:
        checkpoints.append(ReviewCheckpoint(f"checkpoint_{plan.plan_id}_blocker_review", plan.workspace_id, plan.plan_id, "blocker_review", "Blocker review", ["Which blocker can the operator resolve safely?", "Should the task be carried over or cancelled?"], ["Blocked task notes"], ["Resolution or carry-over decision"], blocked_ids))
    if any(x.task_type == "deliverable_generation" for x in plan.tasks):
        checkpoints.append(ReviewCheckpoint(f"checkpoint_{plan.plan_id}_deliverable_review", plan.workspace_id, plan.plan_id, "deliverable_review", "Deliverable review", ["Are claims traceable to evidence?", "Are limitations and next imports explicit?"], ["Deliverable artifacts"], ["Client-ready review decision"], [x.task_id for x in plan.tasks if x.task_type == "deliverable_generation"]))
    return ReviewCadence(f"cadence_{plan.plan_id}", plan.workspace_id, plan.plan_id, checkpoints, metadata={"planning_only": True})


def build_progress_snapshot(plan, completed_task_ids=None, blocked_task_ids=None, cancelled_task_ids=None, produced_outputs=None):
    completed = set(completed_task_ids or []); blocked = set(blocked_task_ids or plan.blocked_task_ids); cancelled = set(cancelled_task_ids or [])
    carried = [x.task_id for x in plan.tasks if x.task_id not in completed | blocked | cancelled and x.status not in {"completed", "cancelled", "skipped"}]
    total = len(plan.tasks); summary = f"{len(completed)}/{total} planned tasks marked completed; {len(blocked)} blocked; {len(carried)} carried over."
    actions = ["Resolve blockers before dependent tasks."] if blocked else ["Review produced outputs and update the next operating plan."]
    if completed or blocked: actions.append("Rerun optimization or executive intelligence after material outputs or changed constraints.")
    return ProgressSnapshot(f"progress_{plan.plan_id}_{int(time.time() * 1000)}", plan.workspace_id, plan.plan_id, sorted(completed), sorted(blocked), carried, sorted(cancelled), produced_outputs or [], summary, [x.blocker_reasons[0] for x in plan.tasks if x.task_id in blocked and x.blocker_reasons], actions, metadata={"planning_only": True})
