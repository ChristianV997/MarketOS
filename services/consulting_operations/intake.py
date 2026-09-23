from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Mapping

@dataclass
class ConsultingIntake:
    client_id: str
    workspace_id: str
    package_selection: str
    scope_description: str
    evidence_coverage: dict[str, Any] = field(default_factory=dict)
    business_context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id,
            "workspace_id": self.workspace_id,
            "package_selection": self.package_selection,
            "scope_description": self.scope_description,
            "evidence_coverage": self.evidence_coverage,
            "business_context": self.business_context
        }

def validate_consulting_intake(payload: Mapping[str, Any]) -> ConsultingIntake:
    """Validates and parses raw consulting intake payload."""
    client_id = payload.get("client_id")
    workspace_id = payload.get("workspace_id")
    package = payload.get("package_selection")
    scope = payload.get("scope_description")

    if not client_id or not workspace_id:
        raise ValueError("missing_client_or_workspace_identity")

    if not package or not scope:
        raise ValueError("missing_package_or_scope")

    return ConsultingIntake(
        client_id=str(client_id),
        workspace_id=str(workspace_id),
        package_selection=str(package),
        scope_description=str(scope),
        evidence_coverage=dict(payload.get("evidence_coverage") or {}),
        business_context=dict(payload.get("business_context") or {})
    )
