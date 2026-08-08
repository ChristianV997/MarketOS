from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class GovernanceDecision:
    decision_id: str = ""
    proposal_id: str = ""
    workspace_id: str = ""
    department_id: str = ""
    decided_by_agent_id: str = ""
    decision: str = "pending"
    reason: str = ""
    conditions: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.decision_id:
            seed = f"{self.proposal_id}:{self.workspace_id}:{self.department_id}:{self.decided_by_agent_id}:{self.decision}:{self.created_at}"
            self.decision_id = f"decision_{uuid.uuid5(uuid.NAMESPACE_URL, seed).hex[:16]}"
        if self.decision not in {"pending", "approved", "rejected", "revision_requested", "blocked"}:
            raise ValueError(f"unsupported decision: {self.decision}")
    def to_dict(self) -> dict[str, Any]: return {key: getattr(self, key) for key in self.__dataclass_fields__}
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GovernanceDecision":
        return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})
