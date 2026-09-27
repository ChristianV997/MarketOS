"""Deterministic, fixture-safe consulting engagement orchestration."""

from .orchestrator import (
    ConsultingEngagementError,
    ConsultingEngagementOrchestrator,
    build_consulting_engagement,
    render_consulting_engagement_markdown,
)
from .schemas import (
    ALLOWED_DELIVERABLES,
    EVIDENCE_CLASSES,
    EVIDENCE_STATES,
    OFFERING_KINDS,
    ComponentReportReference,
    ConsultingEngagementRequest,
    ConsultingEngagementResult,
    EvidenceInput,
    ExecutionPlanItem,
)

__all__ = [
    "ALLOWED_DELIVERABLES",
    "EVIDENCE_CLASSES",
    "EVIDENCE_STATES",
    "OFFERING_KINDS",
    "ComponentReportReference",
    "ConsultingEngagementError",
    "ConsultingEngagementOrchestrator",
    "ConsultingEngagementRequest",
    "ConsultingEngagementResult",
    "EvidenceInput",
    "ExecutionPlanItem",
    "build_consulting_engagement",
    "render_consulting_engagement_markdown",
]
