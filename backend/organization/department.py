from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Department:
    department_id: str = ""
    name: str = ""
    description: str = ""
    manager_agent_id: str = ""
    supervisor_agent_ids: list[str] = field(default_factory=list)
    specialist_agent_ids: list[str] = field(default_factory=list)
    reviewer_agent_ids: list[str] = field(default_factory=list)
    service_modules_allowed: list[str] = field(default_factory=list)
    approval_policy_id: str = "default"
    kpis: dict[str, Any] = field(default_factory=dict)
    active: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not self.department_id:
            self.department_id = self.name.strip().lower().replace(" ", "_") or "department"

    def to_dict(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Department":
        return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})

    def allows_service(self, service_name: str) -> bool:
        return self.active and (not self.service_modules_allowed or service_name in self.service_modules_allowed)


def default_departments() -> list[Department]:
    services = {
        "strategy": ["product_research", "customer_intelligence"],
        "product": ["product_research", "unit_economics"],
        "creative": ["creative_growth"], "finance": ["unit_economics", "profit_stack_advisor"],
        "growth": ["creative_growth", "customer_intelligence"],
    }
    names = ["executive", "strategy", "product", "creative", "ads", "commerce", "finance", "growth", "knowledge"]
    return [Department(department_id=name, name=name.title(), service_modules_allowed=services.get(name, [])) for name in names]
