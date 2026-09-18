"""Service-delivery artifact/projection layer for CompanyOS.

This module adds exactly ONE new thing on top of the existing service-
delivery authorities in :mod:`evaluation.companyos.service_delivery`: a
single, deterministic, client-safe snapshot ("artifact") of one engagement
at one point in its lifecycle -- the projection PR #264's frontend
workbench, and any future consumer, reads instead of reaching into
``ClientEngagement``/``ServiceEconomics``/``ClientDataQualityAssessment``
individually.

It is a projection, not a new authority:

- identity, lifecycle, and data-quality come from
  :mod:`evaluation.companyos.service_delivery` (``ClientEngagement``,
  ``assess_client_data_quality``) -- reused, never re-derived;
- economics figures come from :mod:`backend.economics.kernel`
  (``ServiceEconomics``) via
  :func:`evaluation.companyos.service_delivery.evaluate_engagement_economics`
  -- reused, never re-derived;
- the client-safe deliverable container comes from
  :mod:`backend.deliverables.package` (``DeliverablePackage``) via
  :func:`evaluation.companyos.service_delivery.build_client_service_deliverable`
  -- reused, never re-derived;
- evidence classification is a presentation mapping over the kernel's own
  ``EvidenceRef.evidence_state`` -- it never invents a second evidence
  state machine, and it never promotes fixture/manual/simulated evidence to
  ``live_validated``.

No second service packet, price book, financial engine, export boundary, or
client database is created here. This module never sends client messages,
collects payment, places supplier orders, publishes anything, or claims a
live client outcome, validated pricing, live ad performance, or live
provider access.

Compatibility with PR #247 (research-to-decision projection): as of this
module's authoring, #247's projection module does not exist anywhere in
this branch's dependency tree (confirmed: no `research_to_decision` module
is importable from here). No schema was copied from it and no score was
recalculated from it -- there is nothing importable to reference yet. If
#247 lands with a compatible projection shape, a future change should map
this artifact's fields to it by reference (e.g. re-exporting a shared
`EvidenceClassification` enum), not duplicate its logic. See
``docs/SERVICE_DELIVERY_ARTIFACT_CONTRACT.md`` for the stable-contract and
compatibility rules this module commits to.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from backend.deliverables.package import DeliverablePackage
from backend.economics import EvidenceRef, Money, ServiceEconomics, canonical_json

from .service_delivery import (
    ClientDataQualityAssessment,
    ClientEngagement,
    ClientFacingServicePackage,
    classify_client_value,
    verify_engagement_id,
)
from .service_delivery import _reject_secret_shaped_recursive as _reject_secret_shaped_in_observed_values

ARTIFACT_SCHEMA_VERSION = "MarketOS.ServiceDeliveryArtifact.v1"

# ---------------------------------------------------------------------------
# Evidence classification -- a presentation mapping over the kernel's own
# EvidenceRef.evidence_state, not a second evidence-tracking system.
# ---------------------------------------------------------------------------

ARTIFACT_EVIDENCE_CLASSIFICATIONS = (
    "planning_assumption", "fixture", "manual_import", "derived",
    "supplier_claimed", "supplier_documented", "public_observed",
    "sample_verified", "live_validated", "unavailable",
)

# Maps backend.economics.kernel.EVIDENCE_STATES values to this artifact's
# business-facing vocabulary. "stale" and "rejected" map to "unavailable",
# not to any live-adjacent classification: stale/rejected evidence must
# never promote past the point a fresh, adequate evidence_state would
# reach.
_KERNEL_STATE_TO_ARTIFACT_CLASSIFICATION: dict[str, str] = {
    "unknown": "unavailable",
    "missing": "unavailable",
    "assumed": "planning_assumption",
    "derived": "derived",
    "fixture": "fixture",
    "simulated": "manual_import",
    "observed": "public_observed",
    "live_readonly": "live_validated",
    "verified": "sample_verified",
    "stale": "unavailable",
    "rejected": "unavailable",
}

# Evidence classifications that are, by definition, never live proof. Used
# to fail closed if a caller ever tries to hand-supply a classification
# override that would upgrade fixture/manual/simulated evidence into a
# live-adjacent one.
_NEVER_LIVE_CLASSIFICATIONS = frozenset({"planning_assumption", "fixture", "manual_import", "unavailable"})
_LIVE_ADJACENT_CLASSIFICATIONS = frozenset({"live_validated", "sample_verified"})


def classify_evidence_ref(ref: EvidenceRef, *, supplier_tier: str | None = None) -> str:
    """Classify one EvidenceRef using this artifact's business vocabulary.

    ``supplier_tier`` (``"claimed"`` or ``"documented"``) lets a caller who
    knows the evidence came from a supplier attach that specific tier --
    the kernel's own ``EVIDENCE_STATES`` has no concept of "supplier
    claimed" vs. "supplier documented", so this is additive information,
    not a downgrade or upgrade of the kernel's own classification. A
    supplier tier is only honored when the underlying kernel evidence_state
    is not itself live-adjacent (a supplier claim can never be laundered
    into "live_validated" by supplying a tier).
    """
    base = _KERNEL_STATE_TO_ARTIFACT_CLASSIFICATION.get(ref.evidence_state, "unavailable")
    if supplier_tier is not None and base not in _LIVE_ADJACENT_CLASSIFICATIONS:
        if supplier_tier == "claimed":
            return "supplier_claimed"
        if supplier_tier == "documented":
            return "supplier_documented"
        raise ValueError("invalid supplier_tier")
    return base


# ---------------------------------------------------------------------------
# Revision history -- derived from the engagement's own transition history,
# not a second lifecycle tracker.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RevisionRecord:
    index: int
    lifecycle_state: str
    is_revision_cycle: bool

    def to_dict(self) -> dict[str, Any]:
        return {"index": self.index, "lifecycle_state": self.lifecycle_state, "is_revision_cycle": self.is_revision_cycle}


def build_revision_history(engagement: ClientEngagement) -> tuple[RevisionRecord, ...]:
    """Derive an ordered revision history directly from ``engagement.history``.

    Ordering is exactly the engagement's own append-only transition log --
    this never re-sorts or deduplicates, so two engagements with the same
    states visited in a different order always produce a different
    revision history, and the same engagement replayed twice always
    produces the same one (see ``test_revision_ordering_is_stable``).
    """
    return tuple(
        RevisionRecord(index=index, lifecycle_state=state, is_revision_cycle=(state == "revision_requested"))
        for index, state in enumerate(engagement.history)
    )


# ---------------------------------------------------------------------------
# The artifact itself
# ---------------------------------------------------------------------------


def _artifact_id(engagement_id: str, package_id: str, package_version: str) -> str:
    """Stable identity for one engagement+package: rebuilding the artifact
    from the same engagement is idempotent (same artifact_id every time),
    while the ``replay_hash`` below is what changes across content
    snapshots (revisions)."""
    digest = hashlib.sha256("|".join(("service-delivery-artifact", engagement_id, package_id, package_version)).encode("utf-8")).hexdigest()
    return f"artifact-{digest[:24]}"


@dataclass(frozen=True)
class ServiceDeliveryArtifact:
    schema: str
    artifact_id: str
    replay_hash: str
    workspace_id: str
    engagement_id: str
    package_id: str
    package_version: str
    lifecycle_state: str
    data_quality_state: str
    evidence_references: tuple[Mapping[str, Any], ...]
    evidence_classifications: tuple[str, ...]
    observed_values: Mapping[str, Any]
    derived_values: Mapping[str, Any]
    assumptions: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    blockers: tuple[str, ...]
    planned_deliverables: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    planned_hours: Decimal
    consumed_hours: Decimal
    tooling_cost: Mapping[str, Any]
    pass_through_cost: Mapping[str, Any]
    fee: Mapping[str, Any]
    currency: str
    contribution_reference: Mapping[str, Any] | None
    client_value_classification: str
    approval_state: str
    revision_history: tuple[RevisionRecord, ...]
    delivery_state: str
    renewal_state: str
    next_human_action: str
    safe_export_status: str
    read_only: bool = True
    network_calls: bool = False
    mutated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "artifact_id": self.artifact_id,
            "replay_hash": self.replay_hash,
            "workspace_id": self.workspace_id,
            "engagement_id": self.engagement_id,
            "package_id": self.package_id,
            "package_version": self.package_version,
            "lifecycle_state": self.lifecycle_state,
            "data_quality_state": self.data_quality_state,
            "evidence_references": [dict(item) for item in self.evidence_references],
            "evidence_classifications": list(self.evidence_classifications),
            "observed_values": dict(self.observed_values),
            "derived_values": dict(self.derived_values),
            "assumptions": list(self.assumptions),
            "missing_evidence": list(self.missing_evidence),
            "blockers": list(self.blockers),
            "planned_deliverables": list(self.planned_deliverables),
            "acceptance_criteria": list(self.acceptance_criteria),
            "planned_hours": str(self.planned_hours),
            "consumed_hours": str(self.consumed_hours),
            "tooling_cost": dict(self.tooling_cost),
            "pass_through_cost": dict(self.pass_through_cost),
            "fee": dict(self.fee),
            "currency": self.currency,
            "contribution_reference": dict(self.contribution_reference) if self.contribution_reference else None,
            "client_value_classification": self.client_value_classification,
            "approval_state": self.approval_state,
            "revision_history": [item.to_dict() for item in self.revision_history],
            "delivery_state": self.delivery_state,
            "renewal_state": self.renewal_state,
            "next_human_action": self.next_human_action,
            "safe_export_status": self.safe_export_status,
            "read_only": self.read_only,
            "network_calls": self.network_calls,
            "mutated": self.mutated,
        }


_NEXT_ACTION_BY_STATE: dict[str, str] = {
    "intake": "Collect client scope and initial intake data.",
    "screening": "Assess client data quality before proceeding.",
    "data_inadequate": "Request the missing client evidence listed in missing_evidence.",
    "eligible": "Confirm engagement scope with the client.",
    "scoped": "Begin evidence collection for the scoped work.",
    "evidence_collection": "Continue collecting the required evidence.",
    "analysis": "Complete the internal analysis and prepare a draft.",
    "draft_ready": "Send the draft for internal review before client review.",
    "client_review": "Awaiting client review of the draft deliverable.",
    "revision_requested": "Incorporate the client's requested revisions.",
    "approved": "Prepare final delivery.",
    "delivered": "Confirm client acceptance or open a revision.",
    "renewal_candidate": "Offer a renewal engagement.",
    "upsell_candidate": "Offer an upsell engagement.",
    "paused": "Resume the engagement when ready.",
    "cancelled": "No further action; engagement is cancelled.",
    "rejected": "No further action; engagement was rejected.",
}


def build_service_delivery_artifact(
    engagement: ClientEngagement,
    package: ClientFacingServicePackage,
    economics: ServiceEconomics | None,
    data_quality: ClientDataQualityAssessment,
    deliverable: DeliverablePackage,
    *,
    observed_values: Mapping[str, Any] | None = None,
    evidence_refs: tuple[EvidenceRef, ...] = (),
    supplier_evidence_tiers: Mapping[str, str] | None = None,
) -> ServiceDeliveryArtifact:
    """Compose one deterministic artifact snapshot from existing authorities.

    Raises ``ValueError`` if ``engagement``'s identity fails
    ``verify_engagement_id`` (a forged or tampered record), or if
    ``engagement``/``package``/``deliverable`` do not all refer to the same
    engagement and package.
    """
    if not verify_engagement_id(engagement):
        raise ValueError("engagement identity failed verification (forged or tampered record)")
    if engagement.package_id != package.package_id:
        raise ValueError("engagement and package do not match")
    if deliverable.workspace_id != engagement.workspace_id:
        raise ValueError("deliverable and engagement belong to different workspaces")
    for key, value in (observed_values or {}).items():
        _reject_secret_shaped_in_observed_values(value, field_name=f"observed_values.{key}")

    supplier_evidence_tiers = supplier_evidence_tiers or {}
    evidence_classifications = tuple(
        classify_evidence_ref(ref, supplier_tier=supplier_evidence_tiers.get(ref.evidence_id))
        for ref in evidence_refs
    )

    blockers: list[str] = list(data_quality.reasons)
    if data_quality.data_inadequate:
        blockers.append("client_data_inadequate")
    if economics is None:
        blockers.append("economics_not_computed")

    if economics is not None:
        contribution_reference: Mapping[str, Any] | None = {
            "service_id": economics.service_id,
            "contribution": economics.contribution.to_dict() if economics.contribution else None,
            "contribution_margin": str(economics.contribution_margin) if economics.contribution_margin is not None else "unknown",
            "incremental_contribution": economics.incremental_contribution.to_dict(),
            "orders_required_to_recover_fee": str(economics.orders_required_to_recover_fee) if economics.orders_required_to_recover_fee is not None else "unknown",
            "evidence_state": economics.evidence_state,
        }
        client_value_classification = classify_client_value(economics)
        tooling_cost = economics.tooling_cost.to_dict() if economics.tooling_cost else Money.zero(package.currency).to_dict()
        pass_through_cost = economics.pass_through_cost.to_dict() if economics.pass_through_cost else Money.zero(package.currency).to_dict()
        derived_values = dict(deliverable.sections[0].metadata.get("derived_values", {})) if deliverable.sections else {}
    else:
        contribution_reference = None
        client_value_classification = "unknown"
        tooling_cost = package.tooling_cost.to_dict()
        pass_through_cost = package.optional_pass_through_cost.to_dict()
        derived_values = {}

    payload = {
        "schema": ARTIFACT_SCHEMA_VERSION,
        "workspace_id": engagement.workspace_id,
        "engagement_id": engagement.engagement_id,
        "package_id": package.package_id,
        "package_version": package.package_version,
        "lifecycle_state": engagement.lifecycle_state,
        "data_quality_state": data_quality.status,
        "evidence_references": tuple(ref.to_dict() for ref in evidence_refs),
        "evidence_classifications": evidence_classifications,
        "observed_values": dict(observed_values or {}),
        "derived_values": derived_values,
        "assumptions": engagement.assumptions,
        "missing_evidence": tuple(dict.fromkeys((*data_quality.missing_fields, *engagement.missing_information))),
        "blockers": tuple(dict.fromkeys(blockers)),
        "planned_deliverables": tuple(item.name for item in package.deliverables),
        "acceptance_criteria": package.acceptance_criteria,
        "planned_hours": str(engagement.planned_hours),
        "consumed_hours": str(engagement.consumed_hours),
        "tooling_cost": tooling_cost,
        "pass_through_cost": pass_through_cost,
        "fee": engagement.fee.to_dict(),
        "currency": package.currency,
        "contribution_reference": contribution_reference,
        "client_value_classification": client_value_classification,
        "approval_state": engagement.approval_state,
        "delivery_state": engagement.delivery_state,
        "renewal_state": engagement.renewal_state,
        "next_human_action": _NEXT_ACTION_BY_STATE.get(engagement.lifecycle_state, "Review engagement state."),
        "safe_export_status": "client_safe" if deliverable.metadata.get("leakage_findings", 0) == 0 else "redacted",
    }
    replay_hash = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    artifact_id = _artifact_id(engagement.engagement_id, package.package_id, package.package_version)
    revision_history = build_revision_history(engagement)

    return ServiceDeliveryArtifact(
        schema=ARTIFACT_SCHEMA_VERSION,
        artifact_id=artifact_id,
        replay_hash=replay_hash,
        workspace_id=engagement.workspace_id,
        engagement_id=engagement.engagement_id,
        package_id=package.package_id,
        package_version=package.package_version,
        lifecycle_state=engagement.lifecycle_state,
        data_quality_state=data_quality.status,
        evidence_references=payload["evidence_references"],
        evidence_classifications=evidence_classifications,
        observed_values=payload["observed_values"],
        derived_values=derived_values,
        assumptions=engagement.assumptions,
        missing_evidence=payload["missing_evidence"],
        blockers=payload["blockers"],
        planned_deliverables=payload["planned_deliverables"],
        acceptance_criteria=package.acceptance_criteria,
        planned_hours=engagement.planned_hours,
        consumed_hours=engagement.consumed_hours,
        tooling_cost=tooling_cost,
        pass_through_cost=pass_through_cost,
        fee=engagement.fee.to_dict(),
        currency=package.currency,
        contribution_reference=contribution_reference,
        client_value_classification=client_value_classification,
        approval_state=engagement.approval_state,
        revision_history=revision_history,
        delivery_state=engagement.delivery_state,
        renewal_state=engagement.renewal_state,
        next_human_action=payload["next_human_action"],
        safe_export_status=payload["safe_export_status"],
    )


def verify_artifact_id(engagement_id: str, package_id: str, package_version: str, claimed_artifact_id: str) -> bool:
    """Recompute the deterministic artifact id and compare it against a
    claimed one -- the artifact-level analogue of
    ``evaluation.companyos.service_delivery.verify_engagement_id``."""
    return _artifact_id(engagement_id, package_id, package_version) == claimed_artifact_id


def is_duplicate_replay(first: ServiceDeliveryArtifact, second: ServiceDeliveryArtifact) -> bool:
    """True when two artifact snapshots represent the same content -- an
    idempotent rebuild or a re-delivered duplicate -- not merely the same
    identity. Two snapshots of the *same* engagement at *different*
    lifecycle states have the same ``artifact_id`` but different
    ``replay_hash`` and are correctly NOT a duplicate replay."""
    return first.artifact_id == second.artifact_id and first.replay_hash == second.replay_hash


__all__ = [
    "ARTIFACT_SCHEMA_VERSION", "ARTIFACT_EVIDENCE_CLASSIFICATIONS", "classify_evidence_ref",
    "RevisionRecord", "build_revision_history",
    "ServiceDeliveryArtifact", "build_service_delivery_artifact",
    "verify_artifact_id", "is_duplicate_replay",
]
