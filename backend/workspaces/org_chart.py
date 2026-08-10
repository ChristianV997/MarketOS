"""Workspace ownership metadata for provider capability routing.

No agents are started from this module.  Roles identify who must review a
manual/export/read-only connector plan before an operator progresses it.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from backend.providers.capabilities import list_capability_definitions
from backend.providers.vendor_router import recommend_vendor_for_capability


@dataclass(frozen=True)
class AgentRole:
    role_id: str
    title: str
    department: str
    autonomy: str
    forbidden_actions: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PermissionBoundary:
    department: str
    required_approvals: tuple[str, ...]
    allowed_integration_modes: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    canonical_event_types: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Department:
    department_id: str
    name: str
    manager_role: str
    capability_ids: tuple[str, ...]
    mvp_on: bool
    permission_boundary: PermissionBoundary

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["permission_boundary"] = self.permission_boundary.to_dict()
        return data


@dataclass(frozen=True)
class ConnectorAssignment:
    capability_id: str
    vendor_id: str | None
    department: str
    owner_role: str
    integration_mode: str
    approval_required: bool
    mvp_on: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorkspaceOrgChart:
    chart_id: str
    stage: str
    departments: tuple[Department, ...]
    agent_roles: tuple[AgentRole, ...]
    connector_assignments: tuple[ConnectorAssignment, ...]
    safety_statement: str

    def to_dict(self) -> dict[str, Any]:
        return {"chart_id": self.chart_id, "stage": self.stage, "departments": [item.to_dict() for item in self.departments],
                "agent_roles": [item.to_dict() for item in self.agent_roles], "connector_assignments": [item.to_dict() for item in self.connector_assignments],
                "safety_statement": self.safety_statement}


_FORBIDDEN = ("spend", "publish", "send", "order", "payment", "refund", "fulfillment", "launch", "provider_mutation")
_MODE_BY_DEPARTMENT = {
    "CEO / Executive": ("catalog_only",), "Strategy + Risk": ("catalog_only", "manual_export"),
    "Market Research": ("read_only_api", "csv_import", "manual_export"), "Ecommerce Operations": ("read_only_api", "csv_import", "manual_export"),
    "Creative Production": ("manual_export", "csv_import"), "Sales + Support": ("manual_export", "csv_import"),
    "Automation + Integrations": ("catalog_only", "manual_export", "read_only_api"), "Data + Evidence": ("read_only_api", "csv_import", "catalog_only"),
    "AI Ops": ("catalog_only", "manual_export", "gateway"),
}


def build_default_workspace_org_chart(stage: str = "mvp") -> WorkspaceOrgChart:
    definitions = list_capability_definitions()
    by_department: dict[str, list[Any]] = {}
    for definition in definitions:
        by_department.setdefault(definition.owning_department, []).append(definition)
    departments: list[Department] = []
    roles: list[AgentRole] = []
    assignments: list[ConnectorAssignment] = []
    for department_name in ("CEO / Executive", "Strategy + Risk", "Market Research", "Ecommerce Operations", "Creative Production", "Sales + Support", "Automation + Integrations", "Data + Evidence", "AI Ops"):
        items = sorted(by_department.get(department_name, ()), key=lambda item: item.capability_id)
        event_types = tuple(sorted({event for item in items for event in item.canonical_event_types}))
        manager_role = (items[0].default_agent_role if items else "executive_operator")
        boundary = PermissionBoundary(department_name, ("human_operator",), _MODE_BY_DEPARTMENT[department_name], _FORBIDDEN, event_types)
        departments.append(Department(department_name.lower().replace(" ", "_").replace("+", "and").replace("/", "and"), department_name, manager_role, tuple(item.capability_id for item in items), any("mvp" in item.allowed_mvp_modes for item in items), boundary))
        roles.append(AgentRole(manager_role, manager_role.replace("_", " ").title(), department_name, "advisory_or_operator_assist_only", _FORBIDDEN))
        for item in items:
            route = recommend_vendor_for_capability(item.capability_id, stage)
            mode = "catalog_only"
            if route.recommended_vendor_id:
                from backend.providers.vendor_router import list_vendors_by_capability
                selected = next(record for record in list_vendors_by_capability(item.capability_id) if record.vendor_id == route.recommended_vendor_id)
                mode = selected.integration_mode.value
            assignments.append(ConnectorAssignment(item.capability_id, route.recommended_vendor_id, department_name, item.default_agent_role, mode, bool(route.required_approvals), bool(route.recommended_vendor_id)))
    return WorkspaceOrgChart("marketos-default-org-chart", stage, tuple(departments), tuple(roles), tuple(assignments), "Metadata only: no department or role can initiate live provider mutation, spend, publishing, payment, or messaging.")


__all__ = ["AgentRole", "ConnectorAssignment", "Department", "PermissionBoundary", "WorkspaceOrgChart", "build_default_workspace_org_chart"]
