from __future__ import annotations
import json
import hashlib
from dataclasses import dataclass, field
from typing import Any, Mapping

from .intake import ConsultingIntake, validate_consulting_intake

KNOWN_PACKAGES = {
    "strategy_review": {"effort_hours": 10, "revision_limits": 1, "milestones": ["discovery", "analysis", "delivery"]},
    "market_validation": {"effort_hours": 25, "revision_limits": 2, "milestones": ["intake", "research", "economics", "delivery"]},
    "growth_audit": {"effort_hours": 40, "revision_limits": 2, "milestones": ["intake", "ad_audit", "funnel_audit", "delivery"]}
}

@dataclass
class ConsultingReadinessReport:
    workspace_id: str
    package_selection: str
    intake_complete: bool
    readiness_status: str
    effort_estimates: dict[str, Any]
    milestones: list[str]
    revision_limits: int
    blockers: list[str] = field(default_factory=list)
    safe_handoff_ready: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "package_selection": self.package_selection,
            "intake_complete": self.intake_complete,
            "readiness_status": self.readiness_status,
            "effort_estimates": self.effort_estimates,
            "milestones": self.milestones,
            "revision_limits": self.revision_limits,
            "blockers": self.blockers,
            "safe_handoff_ready": self.safe_handoff_ready
        }

    def compute_fingerprint(self) -> str:
        payload_bytes = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(payload_bytes).hexdigest()


def evaluate_consulting_readiness(intake_payload: Mapping[str, Any]) -> ConsultingReadinessReport:
    """
    Evaluates operational deliverability of consulting packages.
    Fail-closed design based on intake completeness, scope, and evidence coverage.
    No live capabilities like billing, CRM updates, or messaging are executed.
    """
    try:
        intake = validate_consulting_intake(intake_payload)
    except ValueError as e:
        return ConsultingReadinessReport(
            workspace_id=intake_payload.get("workspace_id", "unknown"),
            package_selection=intake_payload.get("package_selection", "unknown"),
            intake_complete=False,
            readiness_status="blocked",
            effort_estimates={},
            milestones=[],
            revision_limits=0,
            blockers=[f"intake_validation_failed: {str(e)}"],
            safe_handoff_ready=False
        )

    blockers = []

    # 1. Package Selection Validation
    pkg_spec = KNOWN_PACKAGES.get(intake.package_selection)
    if not pkg_spec:
        blockers.append("unknown_package_selection")
        effort_estimates = {}
        milestones = []
        revision_limits = 0
    else:
        effort_estimates = {"total_hours": pkg_spec["effort_hours"]}
        milestones = pkg_spec["milestones"]
        revision_limits = pkg_spec["revision_limits"]

    # 2. Evidence Coverage Check
    coverage = intake.evidence_coverage
    if not coverage:
        blockers.append("missing_evidence_coverage")
    else:
        # Example validation: if market validation, require market data
        if intake.package_selection == "market_validation" and not coverage.get("has_market_data"):
            blockers.append("insufficient_evidence_for_market_validation")

    # 3. Scope Completeness
    if len(intake.scope_description.split()) < 10:
        blockers.append("scope_description_too_brief")

    # Determine Readiness Status
    if blockers:
        readiness_status = "blocked"
        safe_handoff = False
        intake_complete = False
    else:
        readiness_status = "ready_for_delivery"
        safe_handoff = True
        intake_complete = True

    return ConsultingReadinessReport(
        workspace_id=intake.workspace_id,
        package_selection=intake.package_selection,
        intake_complete=intake_complete,
        readiness_status=readiness_status,
        effort_estimates=effort_estimates,
        milestones=milestones,
        revision_limits=revision_limits,
        blockers=blockers,
        safe_handoff_ready=safe_handoff
    )
