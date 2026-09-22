"""Consulting Operations Service Layer.

This module evaluates whether a consulting package is operationally deliverable
using existing service contracts, workspace, report, evidence, and delivery structures.
It determines the readiness of an engagement for internal review or client delivery.
"""
from __future__ import annotations

from .schemas import (
    ConsultingEngagement,
    ConsultingMilestone,
    ConsultingReadinessReport,
    ConsultingStatus,
)
from .readiness import (
    evaluate_consulting_readiness,
    generate_readiness_report,
)

__all__ = [
    "ConsultingEngagement",
    "ConsultingMilestone",
    "ConsultingReadinessReport",
    "ConsultingStatus",
    "evaluate_consulting_readiness",
    "generate_readiness_report",
]
