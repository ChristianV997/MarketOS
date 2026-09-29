"""Build safe consulting proposals from the canonical offer catalog."""
from __future__ import annotations

from typing import Any, Mapping

from backend.organization.report_registry import ReportRegistry, get_report_registry
from backend.workspaces.artifact_store import ArtifactStore
from backend.workspaces.client_workspace import ClientWorkspace
from backend.workspaces.registry import WorkspaceRegistry, get_workspace_registry
from evaluation.commerce.kernel_integration import replay_fingerprint
from evaluation.trustos.client_workspace_isolation import export_client_evidence

from .catalog import get_offer_definition
from .schemas import (
    ComponentReportReference,
    ConsultingOfferProposal,
    ConsultingOfferRequest,
    EvidenceInput,
    OfferDefinition,
    SchemaValidationError,
)


class ConsultingOfferCatalogError(ValueError):
    """Stable proposal failure without reflecting untrusted request values."""


def _dedupe(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _assert_workspace(
    workspace: ClientWorkspace,
    request: ConsultingOfferRequest,
    registry: WorkspaceRegistry,
) -> ClientWorkspace:
    if not isinstance(workspace, ClientWorkspace):
        raise ConsultingOfferCatalogError("workspace_identity_rejected")
    if workspace.workspace_id != request.workspace_id:
        raise ConsultingOfferCatalogError("workspace_identity_mismatch")
    registered = registry.get(workspace.workspace_id)
    if registered is None or registered.to_dict() != workspace.to_dict():
        raise ConsultingOfferCatalogError("workspace_identity_rejected")
    if registered.workspace_type != "client_service":
        raise ConsultingOfferCatalogError("workspace_not_client_service")
    return registered


def _report_references(
    request: ConsultingOfferRequest,
    registry: ReportRegistry,
    workspace_id: str,
) -> tuple[ComponentReportReference, ...]:
    references: list[ComponentReportReference] = []
    for report_id in request.linked_component_report_ids:
        report = registry.get(report_id)
        if report is None:
            raise ConsultingOfferCatalogError("component_report_unavailable")
        if report.workspace_id != workspace_id:
            raise ConsultingOfferCatalogError("component_report_workspace_mismatch")
        references.append(ComponentReportReference(
            report_id=report.report_id,
            service_name=report.service_name,
            status=report.status,
            workspace_id=report.workspace_id,
            experiment_id=report.experiment_id,
        ))
    return tuple(references)


def _evidence_summary(evidence: tuple[EvidenceInput, ...]) -> dict[str, Any]:
    class_counts: dict[str, int] = {}
    state_counts: dict[str, int] = {}
    for item in evidence:
        class_counts[item.evidence_class] = class_counts.get(item.evidence_class, 0) + 1
        state_counts[item.state] = state_counts.get(item.state, 0) + 1
    live_authoritative = any(
        item.evidence_class == "live" and item.authoritative and item.state == "available"
        for item in evidence
    )
    weak_classes = {"fixture", "manual", "manual_import", "simulated", "planned", "derived"}
    return {
        "class_counts": dict(sorted(class_counts.items())),
        "state_counts": dict(sorted(state_counts.items())),
        "evidence_ceiling": "live_authoritative_only" if live_authoritative else "fixture_manual_simulated_or_planned",
        "live_authoritative_evidence": live_authoritative,
        "launch_authorized": False,
        "claims_level": "planning_only",
        "weak_evidence_present": any(item.evidence_class in weak_classes for item in evidence),
        "raw_provider_payloads_exported": False,
    }


def _required_evidence(offers: tuple[OfferDefinition, ...]) -> tuple[str, ...]:
    return _dedupe([item for offer in offers for item in offer.evidence_requirements])


def _safe_offer_projection(offer: OfferDefinition) -> dict[str, Any]:
    return {
        "offer_id": offer.offer_id,
        "name": offer.name,
        "summary": offer.summary,
        "price_range": offer.price_range.to_dict(),
        "deliverables": list(offer.deliverables),
        "exclusions": list(offer.exclusions),
        "turnaround_days": offer.turnaround_days,
    }


def _safe_export_payload(projection: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "workspace_id": projection["workspace_id"],
        "status": projection["status"],
        "blockers": list(projection["blockers"]),
        "evidence_required": list(projection["evidence_required"]),
        "approvals_required": list(projection["approvals_required"]),
        "next_actions": [projection["next_action"]],
    }


def _parse_request(request: ConsultingOfferRequest | Mapping[str, Any]) -> ConsultingOfferRequest:
    try:
        return request if isinstance(request, ConsultingOfferRequest) else ConsultingOfferRequest.from_mapping(request)
    except SchemaValidationError as exc:
        raise ConsultingOfferCatalogError(str(exc)) from None


def build_consulting_offer_proposal(
    request: ConsultingOfferRequest | Mapping[str, Any],
    *,
    workspace: ClientWorkspace,
    artifact_store: ArtifactStore,
    workspace_registry: WorkspaceRegistry | None = None,
    report_registry: ReportRegistry | None = None,
) -> ConsultingOfferProposal:
    """Return a deterministic, read-only offer proposal and SOW draft.

    The caller supplies already-bound workspace and artifact authorities. This
    adapter never constructs a store, writes a file, calls a provider, or
    executes a service. Component services and reports remain references.
    """
    parsed = _parse_request(request)
    workspace_registry = workspace_registry or get_workspace_registry()
    report_registry = report_registry or get_report_registry()
    registered = _assert_workspace(workspace, parsed, workspace_registry)
    if not isinstance(artifact_store, ArtifactStore) or artifact_store.workspace.to_dict() != registered.to_dict():
        raise ConsultingOfferCatalogError("artifact_workspace_boundary_rejected")

    try:
        offers = tuple(get_offer_definition(item) for item in parsed.selected_offer_ids)
        upsells = tuple(get_offer_definition(item) for item in parsed.optional_upsell_offer_ids)
    except KeyError:
        raise ConsultingOfferCatalogError("offer_reference_rejected") from None
    references = _report_references(parsed, report_registry, registered.workspace_id)
    evidence_summary = _evidence_summary(parsed.evidence)
    required_evidence = _required_evidence(offers)
    blockers: list[str] = []
    if parsed.offering_kind == "unknown":
        blockers.extend(("offering_kind_unknown", "offer_selection_blocked_until_classified"))
    for offer in offers:
        if parsed.offering_kind not in offer.supported_offering_kinds:
            blockers.append(f"offer_not_applicable:{offer.offer_id}")
        if parsed.pricing_currency != offer.price_range.currency:
            blockers.append(f"price_currency_mismatch:{offer.offer_id}")
    if not parsed.evidence:
        status_without_evidence = "needs_evidence"
    else:
        status_without_evidence = "draft_ready"
    if any(item.state == "missing" for item in parsed.evidence) or parsed.missing_information:
        blockers.append("evidence_missing")
    if any(item.state in {"stale", "conflicting", "blocked", "unavailable"} for item in parsed.evidence):
        blockers.append("evidence_not_current")
    if parsed.conflicts:
        blockers.append("evidence_conflict")
    blockers = list(_dedupe(blockers))
    status = "blocked" if blockers else status_without_evidence
    proposal_id = "proposal-" + replay_fingerprint({"request": parsed.fingerprint, "offers": [item.offer_id for item in offers]})[:24]
    try:
        artifact_store.path_for(proposal_id, "proposal.json")
    except Exception:
        raise ConsultingOfferCatalogError("artifact_workspace_boundary_rejected") from None

    next_action = (
        "Resolve the listed offer, evidence, currency, and scope blockers before client review."
        if blockers else "Review the planning-only proposal and confirm scope, evidence, and human review points."
    )
    price_ranges = tuple(item.price_range for item in offers)
    safe_offer_rows = [_safe_offer_projection(item) for item in offers]
    safe_upsells = [_safe_offer_projection(item) for item in upsells]
    component_reports = [item.to_dict() for item in references]
    proposal_draft = {
        "title": "Consulting offer proposal",
        "client_objective": parsed.client_objective,
        "geography": parsed.geography,
        "language": parsed.language,
        "offering_kind": parsed.offering_kind,
        "offers": safe_offer_rows,
        "price_ranges": [item.to_dict() for item in price_ranges],
        "status": status,
        "evidence_ceiling": evidence_summary["evidence_ceiling"],
        "assumptions": list(parsed.assumptions) + [item for offer in offers for item in offer.assumptions],
        "next_action": next_action,
        "planning_only": True,
    }
    if parsed.consulting_engagement_id is not None:
        proposal_draft["engagement_reference"] = {
            "engagement_id": parsed.consulting_engagement_id,
            "status": "reference_only",
            "authority": "optional_unmerged_on_main",
        }
    sow_draft = {
        "scope": parsed.scope,
        "deliverables": [item for offer in offers for item in offer.deliverables],
        "required_inputs": [item for offer in offers for item in offer.required_inputs],
        "exclusions": [item for offer in offers for item in offer.exclusions],
        "human_review_points": [item for offer in offers for item in offer.human_review_points],
        "turnaround_days": max(item.turnaround_days for item in offers),
        "upgrade_paths": [item.offer_id for item in upsells],
        "planning_only": True,
    }
    safe_projection = {
        "proposal_id": proposal_id,
        "workspace_id": registered.workspace_id,
        "client_id": parsed.client_id,
        "offering_kind": parsed.offering_kind,
        "status": status,
        "offers": safe_offer_rows,
        "price_ranges": [item.to_dict() for item in price_ranges],
        "scope": parsed.scope,
        "geography": parsed.geography,
        "language": parsed.language,
        "evidence_summary": evidence_summary,
        "evidence_required": list(required_evidence),
        "assumptions": list(proposal_draft["assumptions"]),
        "exclusions": list(sow_draft["exclusions"]),
        "human_review_points": list(sow_draft["human_review_points"]),
        "turnaround_days": sow_draft["turnaround_days"],
        "upgrade_paths": safe_upsells,
        "component_reports": component_reports,
        "blockers": blockers,
        "next_action": next_action,
        "read_only": True,
        "live_actions_taken": False,
        "database_writes": False,
    }
    trustos_export = export_client_evidence(
        workspace=registered,
        registry=workspace_registry,
        provenance=f"derived://consulting-offers/{proposal_id}",
        evidence_state="requires_review",
        payload=_safe_export_payload({**safe_projection, "approvals_required": ["client_scope_review", "human_evidence_review"]}),
    ).to_dict()
    internal_fingerprint = replay_fingerprint({
        "request_fingerprint": parsed.fingerprint,
        "offers": [item.to_dict() for item in offers],
        "status": status,
        "blockers": blockers,
        "component_reports": component_reports,
        "proposal_draft": proposal_draft,
        "sow_draft": sow_draft,
        "trustos_export": trustos_export,
    })
    return ConsultingOfferProposal(
        proposal_id=proposal_id,
        client_id=parsed.client_id,
        workspace_id=registered.workspace_id,
        offering_kind=parsed.offering_kind,
        selected_offers=offers,
        status=status,
        price_ranges=price_ranges,
        evidence_summary=evidence_summary,
        component_reports=references,
        proposal_draft=proposal_draft,
        sow_draft=sow_draft,
        client_safe_projection=safe_projection,
        trustos_export=trustos_export,
        blockers=tuple(blockers),
        next_action=next_action,
        fingerprint=internal_fingerprint,
    )


def render_consulting_offer_markdown(proposal: ConsultingOfferProposal) -> str:
    return proposal.to_markdown()


__all__ = ["ConsultingOfferCatalogError", "build_consulting_offer_proposal", "render_consulting_offer_markdown"]
