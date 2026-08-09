from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

STATUSES = {"draft", "proposed", "under_review", "approved", "rejected", "revision_requested", "executing", "completed", "blocked"}
VALID_TRANSITIONS = {
    "draft": {"proposed"}, "proposed": {"under_review", "blocked"},
    "under_review": {"approved", "rejected", "revision_requested", "blocked"},
    "approved": {"executing", "blocked"}, "executing": {"completed", "blocked"},
    "rejected": set(), "revision_requested": {"proposed", "under_review", "blocked"},
    "completed": set(), "blocked": set(),
}


@dataclass
class Proposal:
    proposal_id: str = ""
    workspace_id: str = ""
    department_id: str = ""
    proposed_by_agent_id: str = ""
    title: str = ""
    summary: str = ""
    service_name: str = ""
    requested_budget: float = 0.0
    risk_level: str = "low"
    status: str = "draft"
    linked_experiment_id: str | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    reviewer_findings: list[Any] = field(default_factory=list)
    approval_refs: list[str] = field(default_factory=list)
    obsidian_note_path: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not self.proposal_id:
            seed = f"{self.workspace_id}:{self.department_id}:{self.proposed_by_agent_id}:{self.service_name}:{self.title}:{self.created_at}"
            self.proposal_id = f"proposal_{uuid.uuid5(uuid.NAMESPACE_URL, seed).hex[:16]}"
        if self.status not in STATUSES: raise ValueError(f"unsupported proposal status: {self.status}")

    def can_transition(self, new_status: str) -> bool:
        return new_status in STATUSES and new_status in VALID_TRANSITIONS.get(self.status, set())

    def transition(self, new_status: str, reason: str = "", *, strict: bool = False) -> dict[str, Any]:
        if not self.can_transition(new_status):
            result = {"allowed": False, "status": self.status, "requested_status": new_status, "reason": "invalid_transition"}
            if strict: raise ValueError(f"invalid proposal transition: {self.status} -> {new_status}")
            return result
        self.status = new_status
        if reason: self.reviewer_findings.append(reason)
        self.updated_at = time.time()
        return {"allowed": True, "status": self.status, "requested_status": new_status, "reason": reason}

    def mark_proposed(self): return self.transition("proposed")
    def mark_under_review(self): return self.transition("under_review")
    def mark_approved(self): return self.transition("approved")
    def mark_rejected(self, reason: str): return self.transition("rejected", reason)
    def mark_revision_requested(self, reason: str): return self.transition("revision_requested", reason)
    def mark_executing(self, experiment_id: str | None = None):
        self.linked_experiment_id = experiment_id
        return self.transition("executing")
    def mark_completed(self): return self.transition("completed")
    def mark_blocked(self, reason: str): return self.transition("blocked", reason)

    def to_dict(self) -> dict[str, Any]: return {key: getattr(self, key) for key in self.__dataclass_fields__}
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Proposal":
        return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})
