from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Mapping

from backend.deliverables.package import DeliverableArtifact, DeliverablePackage, DeliverableSection
from evaluation.trustos.client_workspace_isolation import check_workspace_leakage

# Allowed keys in the finalized consulting deliverable metadata
ALLOWED_CONSULTING_KEYS = frozenset({
    "evidence_matrix",
    "assumptions",
    "missing_data",
    "economics",
    "market_findings",
    "supplier_findings",
    "logistics_findings",
    "customer_strategy",
    "marketing_strategy",
    "blockers",
    "confidence",
    "limitations",
    "recommendation",
    "next_action",
    "validation_plan",
    "linked_report_ids",
    "review_required",
    "human_approval_checklist",
    "status"
})

@dataclass
class ConsultingDeliveryPackage:
    """A client-safe delivery package that accepts component reports and produces a coherent consulting deliverable."""
    package_id: str
    workspace_id: str
    title: str
    objective: str
    executive_summary: str
    metadata: dict[str, Any] = field(default_factory=dict)
    sections: list[DeliverableSection] = field(default_factory=list)
    artifacts: list[DeliverableArtifact] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    status: str = "review_required"
    created_at: float = field(default_factory=time.time)

    def __post_init__(self):
        # Every package remains review-required until a separate human-controlled
        # process handles approval or delivery; this layer must not expose those
        # states as if it had authority to grant them.
        if self.status != "review_required":
            self.status = "review_required"

        # Scrub metadata to only allow safe keys
        safe_metadata = {}
        for k, v in self.metadata.items():
            if k in ALLOWED_CONSULTING_KEYS:
                safe_metadata[k] = v
        self.metadata = safe_metadata

        # Set human approval checklist
        if "human_approval_checklist" not in self.metadata:
            self.metadata["human_approval_checklist"] = {
                "legal_review_completed": False,
                "tax_review_completed": False,
                "economics_verified": False,
                "supplier_verified": False
            }

        self.metadata["review_required"] = self.status == "review_required"

    def to_dict(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id,
            "workspace_id": self.workspace_id,
            "package_type": "client_consulting_deliverable",
            "title": self.title,
            "objective": self.objective,
            "executive_summary": self.executive_summary,
            "status": self.status,
            "metadata": self.metadata,
            "sections": [s.to_dict() for s in sorted(self.sections, key=lambda x: x.order)],
            "artifacts": [a.to_dict() for a in self.artifacts],
            "recommendations": self.recommendations,
            "risk_flags": self.risk_flags,
            "missing_evidence": self.missing_evidence,
            "next_actions": self.next_actions,
            "created_at": self.created_at
        }

    def compute_fingerprint(self) -> str:
        """Deterministic fingerprint based on core content, ignoring timestamps."""
        data = self.to_dict()
        data.pop("created_at", None)
        # Ensure deterministic section ordering
        if "sections" in data:
            data["sections"] = sorted(data["sections"], key=lambda x: x.get("order", 0))

        payload_bytes = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(payload_bytes).hexdigest()

    def as_deliverable_package(self) -> DeliverablePackage:
        """Render to the canonical DeliverablePackage for downstream systems."""
        return DeliverablePackage(
            package_id=self.package_id,
            workspace_id=self.workspace_id,
            package_type="client_consulting_deliverable",
            title=self.title,
            objective=self.objective,
            executive_summary=self.executive_summary,
            status=self.status,
            metadata=self.metadata,
            sections=sorted(self.sections, key=lambda x: x.order),
            artifacts=self.artifacts,
            recommendations=self.recommendations,
            risk_flags=self.risk_flags,
            missing_evidence=self.missing_evidence,
            next_actions=self.next_actions,
            created_at=self.created_at
        )


def build_consulting_delivery(
    workspace_id: str,
    package_id: str,
    title: str,
    objective: str,
    executive_summary: str,
    metadata: Mapping[str, Any],
    sections: list[DeliverableSection] | None = None,
    artifacts: list[DeliverableArtifact] | None = None,
    recommendations: list[str] | None = None,
    risk_flags: list[str] | None = None,
    missing_evidence: list[str] | None = None,
    next_actions: list[str] | None = None,
) -> ConsultingDeliveryPackage:

    # 1. Cross-workspace rejection: if metadata claims a different workspace, reject.
    claimed_workspace = metadata.get("workspace_id")
    if claimed_workspace and claimed_workspace != workspace_id:
        raise ValueError("cross_workspace_leakage")

    # 2. Scrub metadata to only allow safe keys before boundary checks
    safe_metadata = {}
    for k, v in metadata.items():
        if k in ALLOWED_CONSULTING_KEYS:
            safe_metadata[k] = v

    # 3. Internal boundary check (redacts credentials, cross-client leaks)
    leakage = check_workspace_leakage(safe_metadata, client_safe=True)
    if leakage:
        raise ValueError("workspace_isolation_violation")

    pkg = ConsultingDeliveryPackage(
        package_id=package_id,
        workspace_id=workspace_id,
        title=title,
        objective=objective,
        executive_summary=executive_summary,
        metadata=safe_metadata,
        sections=sections or [],
        artifacts=artifacts or [],
        recommendations=recommendations or [],
        risk_flags=risk_flags or [],
        missing_evidence=missing_evidence or [],
        next_actions=next_actions or []
    )

    # Render sections deterministically and handle partial/missing data gracefully
    if not pkg.sections:
        pkg.sections.append(DeliverableSection(
            section_id="summary",
            title="Summary",
            order=1,
            content_markdown="Awaiting complete report data."
        ))

    return pkg
