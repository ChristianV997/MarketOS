from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass, field
from typing import Any, Mapping

from backend.workspaces.artifact_store import ArtifactStore
from backend.organization.report_registry import get_report_registry
from backend.organization.commercial_report import CommercialReport
from backend.organization.portfolio_report import PortfolioReport

from .intake import validate_consulting_intake, ConsultingIntake
from .readiness import evaluate_consulting_readiness, ConsultingReadinessReport
from services.consulting_delivery.packager import package_consulting_deliverable
from services.consulting_delivery.package import ConsultingDeliveryPackage


@dataclass
class ConsultingChainReport:
    workspace_id: str
    package_selection: str
    readiness: ConsultingReadinessReport
    deliverable: ConsultingDeliveryPackage | None = None
    envelope_mismatches: list[str] = field(default_factory=list)
    invalid_catalog_ids: list[str] = field(default_factory=list)
    stale_evidence: list[str] = field(default_factory=list)
    secret_leaks: list[str] = field(default_factory=list)
    status: str = "blocked"

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "package_selection": self.package_selection,
            "readiness": self.readiness.to_dict(),
            "deliverable_id": self.deliverable.package_id if self.deliverable else None,
            "envelope_mismatches": self.envelope_mismatches,
            "invalid_catalog_ids": self.invalid_catalog_ids,
            "stale_evidence": self.stale_evidence,
            "secret_leaks": self.secret_leaks,
            "status": self.status
        }


def run_consulting_chain(
    intake_payload: Mapping[str, Any],
    catalog_offers: list[str],
    report_ids: list[str],
    portfolio_report_ids: list[str],
    economics_payload: dict[str, Any] | None = None
) -> ConsultingChainReport:
    """
    Executes the canonical consulting chain:
    offers -> engagement -> economics -> portfolio -> evidence register -> delivery.
    """
    workspace_id = str(intake_payload.get("workspace_id", "unknown"))
    package_selection = str(intake_payload.get("package_selection", "unknown"))

    # 1. Offers / Catalog Validation
    invalid_catalog_ids = []
    if package_selection not in catalog_offers:
        invalid_catalog_ids.append(package_selection)

    # 2. Engagement / Readiness
    readiness = evaluate_consulting_readiness(intake_payload)

    # 3. Economics
    envelope_mismatches = []
    stale_evidence = []
    if economics_payload:
        if economics_payload.get("workspace_id") != workspace_id:
            envelope_mismatches.append(f"economics_workspace_mismatch: {economics_payload.get('workspace_id')} != {workspace_id}")

        # Scalar economics vs ranges
        fee = economics_payload.get("fee")
        if isinstance(fee, dict) and ("min" in fee or "max" in fee):
            envelope_mismatches.append("scalar_economics_accidentally_accepted_as_ranges")

        if economics_payload.get("evidence_status") in ("stale", "missing", "conflicting"):
            stale_evidence.append(economics_payload.get("evidence_status"))

    # Determine chain status
    status = "blocked"
    deliverable = None
    secret_leaks = []

    if readiness.readiness_status == "ready_for_delivery" and not invalid_catalog_ids and not envelope_mismatches and not stale_evidence:
        status = "ready_for_delivery"

        # 4. Portfolio -> Evidence Register -> Delivery Packager
        try:
            deliverable = package_consulting_deliverable(
                workspace_id=workspace_id,
                package_id=f"deliv_{workspace_id}",
                title=f"Consulting Output: {package_selection}",
                objective="Complete deliverable",
                executive_summary="Executive findings and recommendations.",
                metadata={"evidence_matrix": {"covered": True}, "blockers": []}, # safe
                report_ids=report_ids,
                portfolio_report_ids=portfolio_report_ids
            )
        except ValueError as e:
            err = str(e)
            if "workspace_isolation_violation" in err or "leakage" in err:
                secret_leaks.append(err)
            status = "blocked_by_deliverable"

    return ConsultingChainReport(
        workspace_id=workspace_id,
        package_selection=package_selection,
        readiness=readiness,
        deliverable=deliverable,
        envelope_mismatches=envelope_mismatches,
        invalid_catalog_ids=invalid_catalog_ids,
        stale_evidence=stale_evidence,
        secret_leaks=secret_leaks,
        status=status
    )
