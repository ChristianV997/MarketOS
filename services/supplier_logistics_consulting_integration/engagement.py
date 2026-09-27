"""services.supplier_logistics_consulting_integration.engagement -- attach a
``services.supplier_logistics_research.SupplierLogisticsReport`` onto an
existing ``evaluation.companyos.service_delivery.ClientEngagement``.

This module does not create a second engagement/lifecycle authority.
``ClientEngagement``, its state machine (``ENGAGEMENT_STATES`` /
``transition_engagement``), and its identity-forgery guard
(``verify_engagement_id``) all remain owned by
``evaluation.companyos.service_delivery``; this module only knows how to
translate one supplier/logistics evidence report into a legal transition
on that existing machine.
"""
from __future__ import annotations

from typing import Any

from backend.economics.kernel import EvidenceRef
from backend.workspaces.client_workspace import ClientWorkspace
from backend.workspaces.registry import WorkspaceRegistry
from evaluation.companyos.service_delivery import (
    ClientEngagement,
    transition_engagement,
    verify_engagement_id,
)
from services.supplier_logistics_research.schemas import SupplierLogisticsReport

from . import controls

# The only two lifecycle_state values this module ever asks
# transition_engagement for -- both are legal targets from
# "evidence_collection" per evaluation.companyos.service_delivery's own
# _ENGAGEMENT_TRANSITIONS table, so this module composes that table rather
# than inventing a shortcut around it.
_EVIDENCE_INADEQUATE_STATE = "data_inadequate"
_EVIDENCE_SUFFICIENT_STATE = "analysis"


def _collect_evidence_refs(report: SupplierLogisticsReport) -> tuple[EvidenceRef, ...]:
    """Every ``EvidenceRef`` reachable from the report's offer, in a fixed,
    deterministic field order. An unknown offering (no goods/service
    profile) simply contributes its own price_evidence, if any."""
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
    refs = [item.evidence_ref for item in candidates if item.evidence_ref is not None]
    seen: set[str] = set()
    ordered: list[EvidenceRef] = []
    for ref in refs:
        if ref.evidence_id not in seen:
            seen.add(ref.evidence_id)
            ordered.append(ref)
    return tuple(ordered)


def _collect_scenario_assumptions(report: SupplierLogisticsReport) -> tuple[str, ...]:
    notes = [scenario.assumptions_note for scenario in report.landed_cost_scenarios if scenario.assumptions_note]
    return tuple(dict.fromkeys(notes))


def _target_lifecycle_state(report: SupplierLogisticsReport) -> str:
    if report.offer.offering_kind == "unknown" or report.blockers:
        return _EVIDENCE_INADEQUATE_STATE
    return _EVIDENCE_SUFFICIENT_STATE


def record_supplier_logistics_evidence(
    engagement: ClientEngagement,
    report: SupplierLogisticsReport,
    *,
    workspace: ClientWorkspace,
    updated_at: str = "offline-deterministic",
    registry: WorkspaceRegistry | None = None,
) -> ClientEngagement:
    """Transition ``engagement`` from ``evidence_collection`` into either
    ``analysis`` (the report has no blockers and a known offering kind) or
    ``data_inadequate`` (an unknown offering, or any blocker), carrying the
    report's own evidence references, assumptions, and missing-information
    list onto the engagement's mutable fields.

    Negative controls enforced before any transition:
    - **workspace mismatch**: ``workspace`` must be the genuine, currently
      registered record for ``engagement.workspace_id`` (see
      ``controls.require_workspace_match``).
    - **candidate-bound identity**: this function does not itself carry a
      candidate_id parameter to check -- the report's own
      ``SupplierLogisticsReport.__post_init__`` (upstream) already enforces
      that ``report.candidate_id == report.offer.identity.candidate_id``;
      this function trusts that invariant rather than re-deriving it.
    - **currency mismatch**: if the offer carries a quoted price, its
      currency must match the engagement's own fee currency (reusing
      ``backend.economics.kernel.CurrencyMismatchError`` via
      ``controls.require_matching_currency`` -- a genuinely new check at
      this boundary, since the upstream report has no engagement to
      compare against).
    - **engagement identity forgery**: ``evaluation.companyos.
      service_delivery.verify_engagement_id`` must pass before this
      function will touch the record at all.
    """
    controls.require_workspace_match(engagement.workspace_id, workspace, registry=registry)
    if not verify_engagement_id(engagement):
        raise ValueError("engagement identity failed verification (forged or tampered record)")
    if engagement.lifecycle_state != "evidence_collection":
        raise ValueError(
            "record_supplier_logistics_evidence requires an engagement in the "
            f"'evidence_collection' lifecycle state, got {engagement.lifecycle_state!r}"
        )
    if report.offer.quoted_price is not None:
        controls.require_matching_currency(
            report.offer.quoted_price, engagement.fee, field_name="report quoted price and engagement fee"
        )

    new_refs = _collect_evidence_refs(report)
    merged_refs = tuple(dict.fromkeys((*engagement.evidence_set, *new_refs)))
    merged_reference_ids = tuple(dict.fromkeys((*engagement.evidence_references, *(item.evidence_id for item in new_refs))))
    merged_assumptions = tuple(dict.fromkeys((*engagement.assumptions, *_collect_scenario_assumptions(report))))
    merged_missing = tuple(dict.fromkeys((*engagement.missing_information, *report.blockers)))

    target_state = _target_lifecycle_state(report)
    changes: dict[str, Any] = {
        "evidence_set": merged_refs,
        "evidence_references": merged_reference_ids,
        "assumptions": merged_assumptions,
        "missing_information": merged_missing,
    }
    return transition_engagement(engagement, target_state, updated_at=updated_at, **changes)
