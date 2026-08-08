from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

STATUSES = {"draft", "proposed", "under_review", "approved", "rejected", "revision_requested", "executing", "completed", "blocked"}


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

    def _set(self, status: str, reason: str | None = None) -> None:
        self.status = status
        if reason: self.reviewer_findings.append(reason)
        self.updated_at = time.time()
    def mark_proposed(self): self._set("proposed")
    def mark_under_review(self): self._set("under_review")
    def mark_approved(self): self._set("approved")
    def mark_rejected(self, reason: str): self._set("rejected", reason)
    def mark_revision_requested(self, reason: str): self._set("revision_requested", reason)
    def mark_executing(self, experiment_id: str | None = None): self.linked_experiment_id = experiment_id; self._set("executing")
    def mark_completed(self): self._set("completed")
    def mark_blocked(self, reason: str): self._set("blocked", reason)

    def to_dict(self) -> dict[str, Any]: return {key: getattr(self, key) for key in self.__dataclass_fields__}
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Proposal":
        return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})
