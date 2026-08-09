from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from .agent_role import AgentRole
from .department import Department, default_departments


def _path() -> Path:
    return Path(os.getenv("MARKETOS_ORGANIZATION_STATE", "state/organization_registry.json"))


class OrganizationRegistry:
    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(path) if path else _path()
        self._agents: dict[str, AgentRole] = {}
        self._departments: dict[str, Department] = {}
        self._lock = threading.RLock()
        self.load()

    def register_agent(self, role: AgentRole) -> AgentRole:
        with self._lock:
            self._agents[role.agent_id] = role
            self.save()
            return role

    def register_department(self, department: Department) -> Department:
        with self._lock:
            self._departments[department.department_id] = department
            self.save()
            return department

    def get_agent(self, agent_id: str) -> AgentRole | None: return self._agents.get(agent_id)
    def get_department(self, department_id: str) -> Department | None: return self._departments.get(department_id)
    def list_agents(self) -> list[AgentRole]: return list(self._agents.values())
    def list_departments(self) -> list[Department]: return list(self._departments.values())
    def agents_for_department(self, department_id: str) -> list[AgentRole]:
        return [a for a in self._agents.values() if a.department_id == department_id]
    def reviewers_for_department(self, department_id: str) -> list[AgentRole]:
        d = self.get_department(department_id)
        ids = set(d.reviewer_agent_ids if d else [])
        return [a for a in self.agents_for_department(department_id) if a.role_type == "reviewer" or a.agent_id in ids]

    def bootstrap_defaults(self) -> dict[str, Any]:
        for department in default_departments():
            self.register_department(department)
            manager = AgentRole(name=f"{department.department_id} manager", department_id=department.department_id,
                                role_type="manager", permissions=["read", "propose", "review"],
                                tools_allowed=department.service_modules_allowed)
            specialist = AgentRole(name=f"{department.department_id} specialist", department_id=department.department_id,
                                   role_type="specialist", permissions=["read", "propose"],
                                   tools_allowed=department.service_modules_allowed)
            reviewer = AgentRole(name=f"{department.department_id} reviewer", department_id=department.department_id,
                                 role_type="reviewer", permissions=["read", "review"],
                                 tools_allowed=department.service_modules_allowed)
            for role in (manager, specialist, reviewer): self.register_agent(role)
            department.manager_agent_id = manager.agent_id
            department.specialist_agent_ids = [specialist.agent_id]
            department.reviewer_agent_ids = [reviewer.agent_id]
            department.updated_at = manager.updated_at
            self.register_department(department)
        return {"status": "ok", "departments": len(self._departments), "agents": len(self._agents)}

    def load(self) -> None:
        try:
            if not self.path.exists(): return
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._agents = {k: AgentRole.from_dict(v) for k, v in raw.get("agents", {}).items() if isinstance(v, dict)}
            self._departments = {k: Department.from_dict(v) for k, v in raw.get("departments", {}).items() if isinstance(v, dict)}
        except Exception:
            self._agents, self._departments = {}, {}

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(self.path.suffix + ".tmp")
            temp.write_text(json.dumps({"agents": {k: v.to_dict() for k, v in self._agents.items()},
                                        "departments": {k: v.to_dict() for k, v in self._departments.items()}}, indent=2), encoding="utf-8")
            temp.replace(self.path)
        except Exception:
            pass


_singleton: OrganizationRegistry | None = None
_singleton_lock = threading.Lock()


def get_organization_registry() -> OrganizationRegistry:
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None: _singleton = OrganizationRegistry()
    return _singleton
