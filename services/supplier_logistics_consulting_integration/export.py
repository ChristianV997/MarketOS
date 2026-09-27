"""services.supplier_logistics_consulting_integration.export -- client-safe
egress for supplier/logistics evidence, built entirely on TrustOS's own
export boundary.

Two export shapes are provided, matching the two shapes the upstream
authorities already define -- neither is re-implemented here:

- ``export_supplier_logistics_status`` calls
  ``evaluation.trustos.client_workspace_isolation.export_client_evidence``
  directly for the narrow, canonical, size-bounded status/blockers/
  next-actions export (payload keys restricted to that function's own
  ``CLIENT_EXPORT_FIELDS`` allowlist -- this module cannot widen it).
- ``build_client_safe_deliverable`` composes
  ``backend.deliverables.package.DeliverablePackage`` /
  ``backend.deliverables.registry.DeliverableRegistry`` (the single
  deliverable-report container this repository already uses for every
  other client deliverable) with
  ``evaluation.trustos.client_workspace_isolation.check_workspace_leakage``
  (the sole internal-to-client leakage detector) for a richer payload.

Neither function calls a supplier, places an order, requests payment, or
authorizes a launch -- both are pure, offline projections of an existing,
already-computed ``SupplierLogisticsReport``.
"""
from __future__ import annotations

import hashlib
from typing import Any

from backend.deliverables.package import DeliverablePackage, DeliverableSection
from backend.deliverables.registry import DeliverableRegistry, get_deliverable_registry
from backend.workspaces.client_workspace import ClientWorkspace
from backend.workspaces.registry import WorkspaceRegistry
from evaluation.companyos.service_delivery import ClientEngagement, ClientFacingServicePackage, verify_engagement_id
from services.supplier_logistics_research.schemas import SupplierLogisticsReport

from . import controls
from .portfolio import _report_id

_EXPORT_PROVENANCE = "derived://supplier_logistics_research"

# report.status values this module never claims -- export_client_evidence's
# own _NON_AUTHORITATIVE_CLAIM_MARKERS check would reject "live"/"actual"/
# "production"-shaped status strings anyway; this module simply never
# produces one, since a report is never more than planning evidence.
_STATUS_UNASSESSED = "unassessed"
_STATUS_NEEDS_REVIEW = "needs_review"
_STATUS_READY_FOR_REVIEW = "ready_for_review"


def _status_label(report: SupplierLogisticsReport) -> str:
    if report.offer.offering_kind == "unknown":
        return _STATUS_UNASSESSED
    if report.blockers:
        return _STATUS_NEEDS_REVIEW
    return _STATUS_READY_FOR_REVIEW


def export_supplier_logistics_status(
    report: SupplierLogisticsReport,
    *,
    workspace: ClientWorkspace,
    registry: WorkspaceRegistry | None = None,
):
    """The narrow, canonical TrustOS client-safe export: workspace_id,
    status, blockers, evidence_required, approvals_required, next_actions
    only -- ``evaluation.trustos.client_workspace_isolation.
    export_client_evidence`` enforces every other safety property
    (identity re-verification, field allowlisting, leakage scan, size
    bound, non-authoritative-claim rejection)."""
    from evaluation.trustos.client_workspace_isolation import export_client_evidence

    verified_workspace = controls.require_workspace_match(workspace.workspace_id, workspace, registry=registry)
    payload: dict[str, Any] = {
        "workspace_id": verified_workspace.workspace_id,
        "status": _status_label(report),
        "blockers": list(report.blockers),
        "evidence_required": [action.description for action in report.next_actions if action.blocking],
        "approvals_required": [],
        "next_actions": [action.description for action in report.next_actions if not action.blocking],
    }
    return export_client_evidence(
        workspace=verified_workspace,
        registry=registry,
        provenance=_EXPORT_PROVENANCE,
        evidence_state="requires_review" if report.blockers else "present",
        payload=payload,
    )


def collect_supplier_notes(report: SupplierLogisticsReport) -> tuple[str, ...]:
    """Every ``FieldEvidence.note`` reachable from the report's offer.

    These are supplier- or operator-authored free text.
    ``services.supplier_logistics_research.schemas.FieldEvidence.
    __post_init__`` only validates that a note contains no control
    characters -- it does NOT screen for secrets, HTML, or cross-client
    references (that screening is opt-in, via
    ``services.supplier_logistics_research.controls.reject_unsafe_input``,
    which the upstream service never calls automatically). Any caller that
    wants to surface these notes to a client MUST run them through that
    screen first -- see ``build_client_safe_deliverable_payload``'s
    ``include_supplier_notes`` path, which does exactly that.
    """
    offer = report.offer
    candidates = [offer.price_evidence]
    if offer.goods is not None:
        candidates.extend([
            offer.goods.supplier_evidence,
            offer.goods.logistics_evidence,
            offer.goods.moq_availability.evidence,
            offer.goods.lead_time.evidence,
            offer.goods.customs.evidence,
            offer.goods.returns_defects.evidence,
            offer.goods.shipping.evidence,
        ])
    if offer.service is not None:
        candidates.append(offer.service.evidence)
    return tuple(dict.fromkeys(item.note for item in candidates if item.note))


def build_client_safe_deliverable_payload(
    report: SupplierLogisticsReport,
    *,
    include_supplier_notes: bool = False,
) -> dict[str, Any]:
    """A richer, still client-safe projection of ``report`` for a
    ``DeliverablePackage`` section. Every field here is either the
    report's own structured, already-curated content (categories,
    severities, our own generated descriptions) or -- only when explicitly
    requested -- supplier free text that has first passed
    ``controls.reject_unsafe_input`` (reused from
    ``services.supplier_logistics_research.controls``, not
    reimplemented). The caller must still run the result through
    ``controls.reject_cross_client_leakage`` before treating it as
    client-safe; this function does not call that itself so a caller can
    inspect what was rejected."""
    payload: dict[str, Any] = {
        "candidate_id": report.candidate_id,
        "offering_kind": report.offer.offering_kind,
        "status": _status_label(report),
        "blockers": list(report.blockers),
        "risk_matrix": [
            {"category": entry.category, "severity": entry.severity, "description": entry.description}
            for entry in report.risk_matrix
        ],
        "next_actions": [
            {"description": action.description, "blocking": action.blocking} for action in report.next_actions
        ],
        "landed_cost_scenarios": [
            {"scenario_id": scenario.scenario_id, "assumptions_note": scenario.assumptions_note}
            for scenario in report.landed_cost_scenarios
        ],
        "evidence_quality_summary": dict(report.evidence_quality_summary),
    }
    if include_supplier_notes:
        notes = collect_supplier_notes(report)
        for note in notes:
            controls.reject_unsafe_input(note, field_name="supplier_note")
        payload["supplier_notes"] = list(notes)
    return payload


def _deliverable_id(engagement: ClientEngagement, report: SupplierLogisticsReport, generated_at: str) -> str:
    digest = hashlib.sha256("|".join((engagement.engagement_id, report.candidate_id, generated_at)).encode("utf-8")).hexdigest()
    return f"supplier-logistics-deliverable-{digest[:24]}"


def build_client_safe_deliverable(
    report: SupplierLogisticsReport,
    *,
    engagement: ClientEngagement,
    package: ClientFacingServicePackage,
    workspace: ClientWorkspace,
    registry: WorkspaceRegistry | None = None,
    deliverable_registry: DeliverableRegistry | None = None,
    include_supplier_notes: bool = False,
    generated_at: str = "offline-deterministic",
) -> DeliverablePackage:
    """Build and register one client-safe ``DeliverablePackage`` for a
    supplier/logistics evidence report attached to ``engagement``.

    Fails closed (raises) rather than silently redacting when the payload
    trips ``evaluation.trustos.client_workspace_isolation.
    check_workspace_leakage`` -- unlike ``evaluation.companyos.
    service_delivery.build_client_service_deliverable``'s best-effort
    redact-after-check pattern, this function never emits a payload that
    the sole leakage authority flagged.
    """
    controls.require_workspace_match(engagement.workspace_id, workspace, registry=registry)
    if not verify_engagement_id(engagement):
        raise ValueError("engagement identity failed verification (forged or tampered record)")
    if engagement.package_id != package.package_id:
        raise ValueError("engagement and package do not match")

    payload = build_client_safe_deliverable_payload(report, include_supplier_notes=include_supplier_notes)
    controls.reject_cross_client_leakage(payload, field_name="supplier_logistics_deliverable_payload")

    status = "blocked" if report.blockers else "completed"
    exec_summary = (
        f"{package.name}: supplier/logistics evidence for candidate {report.candidate_id} is incomplete; "
        f"see blockers before this finding is used in a client deliverable."
        if status == "blocked"
        else f"{package.name}: supplier/logistics evidence for candidate {report.candidate_id} is documented for review."
    )
    section = DeliverableSection(
        section_id="supplier_logistics_evidence",
        title="Supplier & logistics evidence",
        order=1,
        content_markdown=exec_summary,
        summary=exec_summary,
        metadata=payload,
    )
    deliverable_id = _deliverable_id(engagement, report, generated_at)
    package_type = f"client_supplier_logistics_research_{report.offer.offering_kind}"
    dp = DeliverablePackage(
        package_id=deliverable_id,
        workspace_id=engagement.workspace_id,
        package_type=package_type,
        title=f"{package.name}: supplier & logistics evidence for engagement {engagement.engagement_id}",
        objective=package.expected_outcome,
        status=status,
        source_report_ids=[_report_id(report)],
        sections=[section],
        executive_summary=exec_summary,
        recommendations=[action.description for action in report.next_actions if not action.blocking],
        risk_flags=[f"{entry.category}:{entry.severity}" for entry in report.risk_matrix if entry.severity in {"high", "blocked"}],
        missing_evidence=list(report.blockers),
        next_actions=[action.description for action in report.next_actions if action.blocking],
        metadata={
            "currency": package.currency,
            "candidate_id": report.candidate_id,
            "client_id": engagement.client_id,
            "read_only": True,
            "network_calls": False,
            "mutated": False,
        },
    )
    reg = deliverable_registry or get_deliverable_registry()
    reg.register_package(dp)
    return dp
