from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

ROLE_TYPES = {"executive", "manager", "supervisor", "specialist", "reviewer", "librarian"}


def _now() -> float:
    return time.time()


def _stable_id(department_id: str, name: str, role_type: str) -> str:
    raw = f"{department_id}:{name}:{role_type}".strip().lower().encode()
    return f"agent_{hashlib.sha256(raw).hexdigest()[:16]}"


@dataclass
class AgentRole:
    agent_id: str = ""
    name: str = ""
    department_id: str = ""
    role_type: str = "specialist"
    permissions: list[str] = field(default_factory=list)
    tools_allowed: list[str] = field(default_factory=list)
    max_budget_authority: float = 0.0
    requires_review_above: float = 0.0
    workspace_scope: list[str] = field(default_factory=list)
    active: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)

    def __post_init__(self) -> None:
        if self.role_type not in ROLE_TYPES:
            raise ValueError(f"unsupported role_type: {self.role_type}")
        if not self.agent_id:
            self.agent_id = _stable_id(self.department_id, self.name, self.role_type)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id, "name": self.name, "department_id": self.department_id,
            "role_type": self.role_type, "permissions": list(self.permissions),
            "tools_allowed": list(self.tools_allowed), "max_budget_authority": float(self.max_budget_authority),
            "requires_review_above": float(self.requires_review_above), "workspace_scope": list(self.workspace_scope),
            "active": self.active, "metadata": dict(self.metadata), "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentRole":
        return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})

    def can(self, permission: str) -> bool:
        return self.active and (permission in self.permissions or "*" in self.permissions)

    def touch(self) -> None:
        self.updated_at = _now()
