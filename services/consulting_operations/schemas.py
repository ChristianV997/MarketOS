"""Schemas for consulting operations readiness evaluation."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class ConsultingStatus(str, Enum):
    INCOMPLETE = "incomplete"
    BLOCKED = "blocked"
    READY_FOR_REVIEW = "ready_for_review"
    READY_FOR_CLIENT_SERVICE = "ready_for_client_service"


@dataclass(frozen=True)
class ConsultingMilestone:
    name: str
    status: str
    requires_client_input: bool = False
    dependencies: tuple[str, ...] = ()
    completed: bool = False


@dataclass(frozen=True)
class ConsultingEngagement:
    engagement_id: str
    package_id: str
    workspace_id: str
    owner: str
    reviewer: str | None = None
    intake_complete: bool = False
    scope_complete: bool = False
    evidence_provided: tuple[str, ...] = ()
    missing_data_checklist: tuple[str, ...] = ()
    estimated_delivery_effort_hours: float = 0.0
    planned_milestones: tuple[ConsultingMilestone, ...] = ()
    revision_allowance: int = 1
    revisions_used: int = 0
    client_safe_export_status: str = "pending"
    human_review_status: str = "pending"
    handoff_checklist_complete: bool = False
    delivery_status: str = "planning"
    upgrade_readiness: str = "not_evaluated"

    def to_dict(self) -> dict[str, Any]:
        return {
            "engagement_id": self.engagement_id,
            "package_id": self.package_id,
            "workspace_id": self.workspace_id,
            "owner": self.owner,
            "reviewer": self.reviewer,
            "intake_complete": self.intake_complete,
            "scope_complete": self.scope_complete,
            "evidence_provided": self.evidence_provided,
            "missing_data_checklist": self.missing_data_checklist,
            "estimated_delivery_effort_hours": self.estimated_delivery_effort_hours,
            "planned_milestones": [m.__dict__ for m in self.planned_milestones],
            "revision_allowance": self.revision_allowance,
            "revisions_used": self.revisions_used,
            "client_safe_export_status": self.client_safe_export_status,
            "human_review_status": self.human_review_status,
            "handoff_checklist_complete": self.handoff_checklist_complete,
            "delivery_status": self.delivery_status,
            "upgrade_readiness": self.upgrade_readiness,
        }


@dataclass(frozen=True)
class ConsultingReadinessReport:
    engagement_id: str
    status: ConsultingStatus
    blockers: tuple[str, ...]
    next_actions: tuple[str, ...]
    is_client_safe: bool
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "engagement_id": self.engagement_id,
            "status": self.status.value,
            "blockers": list(self.blockers),
            "next_actions": list(self.next_actions),
            "is_client_safe": self.is_client_safe,
            "warnings": list(self.warnings),
        }
