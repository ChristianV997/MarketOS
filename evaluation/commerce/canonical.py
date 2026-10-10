"""Canonical commerce-domain concepts, additive over existing contracts.

This module intentionally does not redefine anything that already has a
canonical home:

  * money, currency safety, market-lane logistics/tax/fee assumptions, and
    evidence identity/freshness/confidence come from the financial-kernel
    lane (``backend.economics.kernel`` — see ``docs/FINANCIAL_EVIDENCE_KERNEL.md``,
    PR #248). ``EvidenceReference`` below is a naming alias for
    ``backend.economics.kernel.EvidenceRef``, not a second schema.
  * product/supplier identity and data-quality provenance come from
    ``evaluation.contracts`` (``ProductCandidate``, ``SupplierOffer``,
    ``DataQuality``).
  * experiment/test-result evaluation comes from ``evaluation.experiments``.

What is genuinely missing from those layers — and what this module adds —
is: competitive evidence (``CompetitionSnapshot``), a single accountable-
ownership map that keeps retail/commission/affiliate/lead-gen businesses
from silently sharing retail-margin assumptions (``BusinessModel``,
``OwnershipAssignment``, ``CommercialOwnership``), promotion-state risk
(``PromotionGate``, ``RiskState``), a canonical commercial ``Offer`` that
composes the above without re-deriving any of it, and a ``ServiceEngagement``
record tying a sold service package to a workspace and its kernel-computed
``ServiceEconomics``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from backend.economics.kernel import EvidenceRef, MarketLane, Money, ServiceEconomics

from evaluation.contracts import DataQuality

# ---------------------------------------------------------------------------
# Compatibility alias: the integration spec's vocabulary calls this concept
# "EvidenceReference"; the canonical financial-kernel lane already defines
# the identical concept as EvidenceRef (identity, source, capture timestamp,
# freshness/valid_until, confidence, evidence_state). Do not create a second
# evidence-identity schema — alias it.
# ---------------------------------------------------------------------------
EvidenceReference = EvidenceRef


@dataclass(frozen=True)
class SupplierOfferIdentity:
    """Exact supplier offer identity required for a commerce packet."""

    supplier_id: str
    offer_id: str
    supplier_sku: str
    variant_id: str = ""
    evidence_ref: EvidenceRef | None = None

    def __post_init__(self) -> None:
        for name in ("supplier_id", "offer_id", "supplier_sku"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or any(ord(char) < 32 for char in value):
                raise ValueError("supplier offer identity is invalid")
        if self.variant_id and (not isinstance(self.variant_id, str) or any(ord(char) < 32 for char in self.variant_id)):
            raise ValueError("supplier offer identity is invalid")
        if self.evidence_ref is not None and not isinstance(self.evidence_ref, EvidenceRef):
            raise ValueError("supplier offer evidence is invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "supplier_id": self.supplier_id,
            "offer_id": self.offer_id,
            "supplier_sku": self.supplier_sku,
            "variant_id": self.variant_id,
            "evidence_ref": self.evidence_ref.to_dict() if self.evidence_ref else None,
        }


class BusinessModel(str, Enum):
    """How MarketOS is compensated for a given commercial Offer.

    Kept as a closed enum, not a free-text field, specifically so a caller
    cannot silently apply retail-margin math (full landed-cost waterfall) to
    a commission/affiliate/lead-generation offer where MarketOS never holds
    inventory or collects the full sale price. See
    ``evaluation.commerce.business_model_economics`` for the dispatch that
    enforces this at the calculation boundary.
    """

    RETAIL_MARGIN = "retail_margin"
    COMMISSION = "commission"
    AFFILIATE = "affiliate"
    LEAD_GENERATION = "lead_generation"


OWNERSHIP_ROLES: tuple[str, ...] = (
    "merchant_of_record",
    "fulfillment_owner",
    "warranty_owner",
    "return_owner",
    "support_owner",
    "payment_collection_owner",
)


@dataclass(frozen=True)
class OwnershipAssignment:
    """One accountable party for a specific operational responsibility.

    ``owner`` is a workspace-scoped descriptive identifier (a company or
    party name), never a mutation authority. ``"unknown"`` is a first-class,
    explicit value — an unassigned role must never be silently defaulted to
    "MarketOS" or "the seller".
    """

    role: str
    owner: str = "unknown"
    evidence_ref: EvidenceRef | None = None

    def __post_init__(self) -> None:
        if self.role not in OWNERSHIP_ROLES:
            raise ValueError(f"unknown ownership role: {self.role}")

    @property
    def is_known(self) -> bool:
        return self.owner not in ("", "unknown", None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "owner": self.owner,
            "known": self.is_known,
            "evidence_ref": self.evidence_ref.to_dict() if self.evidence_ref else None,
        }


@dataclass(frozen=True)
class CommercialOwnership:
    """The full ownership map required before any Offer can launch responsibly.

    ``commission_or_margin_method`` records which formula path
    (retail-margin waterfall vs. commission/affiliate/lead-gen payout) is
    authoritative for this offer — kept alongside ownership because the
    method and the accountable parties are usually decided together (e.g. a
    commission offer implies the merchant, not MarketOS, is the
    merchant_of_record and fulfillment_owner).
    """

    merchant_of_record: OwnershipAssignment
    fulfillment_owner: OwnershipAssignment
    warranty_owner: OwnershipAssignment
    return_owner: OwnershipAssignment
    support_owner: OwnershipAssignment
    payment_collection_owner: OwnershipAssignment
    commission_or_margin_method: str = "unknown"

    @classmethod
    def unknown(cls) -> "CommercialOwnership":
        return cls(*(OwnershipAssignment(role) for role in OWNERSHIP_ROLES))

    def _assignments(self) -> tuple[OwnershipAssignment, ...]:
        return (
            self.merchant_of_record,
            self.fulfillment_owner,
            self.warranty_owner,
            self.return_owner,
            self.support_owner,
            self.payment_collection_owner,
        )

    @property
    def unknown_roles(self) -> tuple[str, ...]:
        return tuple(a.role for a in self._assignments() if not a.is_known)

    @property
    def fully_known(self) -> bool:
        return not self.unknown_roles

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {a.role: a.to_dict() for a in self._assignments()}
        result["commission_or_margin_method"] = self.commission_or_margin_method
        result["unknown_roles"] = list(self.unknown_roles)
        result["fully_known"] = self.fully_known
        return result


@dataclass(frozen=True)
class CompetitionSnapshot:
    """Deterministic competitive-evidence snapshot for one candidate/lane.

    Wraps the same evidence-quality vocabulary already used by the
    marketplace-trend and opportunity-synthesis reports (saturation score,
    observed price band, offer count) rather than re-deriving a second
    competition schema.
    """

    candidate_id: str
    lane_id: str
    observed_offer_count: int = 0
    price_band_min: float | None = None
    price_band_max: float | None = None
    saturation_score: float = 0.0
    dominant_retailer: str = ""
    dominant_retailer_share: float | None = None
    evidence_ref: EvidenceRef | None = None

    @property
    def retailer_dominance_risk(self) -> bool:
        """True when a single retailer plausibly controls the lane's demand."""
        return self.dominant_retailer_share is not None and self.dominant_retailer_share >= 0.5

    @property
    def oversaturated(self) -> bool:
        return self.saturation_score >= 0.7

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "lane_id": self.lane_id,
            "observed_offer_count": self.observed_offer_count,
            "price_band_min": self.price_band_min,
            "price_band_max": self.price_band_max,
            "saturation_score": self.saturation_score,
            "dominant_retailer": self.dominant_retailer,
            "dominant_retailer_share": self.dominant_retailer_share,
            "retailer_dominance_risk": self.retailer_dominance_risk,
            "oversaturated": self.oversaturated,
            "evidence_ref": self.evidence_ref.to_dict() if self.evidence_ref else None,
        }


@dataclass(frozen=True)
class PromotionGate:
    """One named evidence gate that must be satisfied to advance a stage."""

    gate_id: str
    required: bool
    satisfied: bool
    evidence_ref: EvidenceRef | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "required": self.required,
            "satisfied": self.satisfied,
            "evidence_ref": self.evidence_ref.to_dict() if self.evidence_ref else None,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RiskState:
    """Aggregate, deterministic risk read for a candidate/offer at a stage."""

    level: str  # "low" | "medium" | "high" | "blocked"
    blockers: tuple[str, ...] = ()
    open_gates: tuple[str, ...] = ()
    evidence_state: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "blockers": list(self.blockers),
            "open_gates": list(self.open_gates),
            "evidence_state": self.evidence_state,
        }


@dataclass(frozen=True)
class WorkspaceReplayContext:
    """Workspace ownership and replay identity, common to every canonical record.

    The financial-kernel and evaluation.contracts layers are deliberately
    workspace-agnostic (pure economics / pure evidence quality); this is the
    thin, additive context that ties either of them to a specific tenant and
    a specific deterministic run, matching the rest of this repo's
    ``workspace_id`` + ``replay_hash``/``correlation_id`` conventions
    (see ``backend.contracts.events.Event``).
    """

    workspace_id: str = ""
    replay_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"workspace_id": self.workspace_id, "replay_id": self.replay_id}


@dataclass(frozen=True)
class Offer:
    """A canonical commercial offer: identity + lane + business model + ownership.

    Composes existing/kernel types rather than redefining product, supplier,
    money, or evidence schemas. ``stage`` is one of
    ``evaluation.commerce.promotion.STAGES``.
    """

    offer_id: str
    product_id: str
    supplier_id: str
    lane: MarketLane
    business_model: BusinessModel
    ownership: CommercialOwnership
    price: Money
    stage: str = "candidate"
    quality: DataQuality = field(default_factory=DataQuality)
    context: WorkspaceReplayContext = field(default_factory=WorkspaceReplayContext)

    def to_dict(self) -> dict[str, Any]:
        return {
            "offer_id": self.offer_id,
            "product_id": self.product_id,
            "supplier_id": self.supplier_id,
            "lane": self.lane.to_dict(),
            "business_model": self.business_model.value,
            "ownership": self.ownership.to_dict(),
            "price": self.price.to_dict(),
            "stage": self.stage,
            "quality": {
                "provenance": self.quality.provenance,
                "attribution": self.quality.attribution,
                "completeness": self.quality.completeness,
                "observed_at": self.quality.observed_at.isoformat(),
                "source_ref": self.quality.source_ref,
                "retrieval_mode": self.quality.retrieval_mode,
                "is_synthetic": self.quality.is_synthetic,
            },
            "context": self.context.to_dict(),
        }


@dataclass(frozen=True)
class ServiceEngagement:
    """One instance of a sold CompanyOS service package for a workspace.

    ``economics`` is the kernel's ``ServiceEconomics`` (never re-derived
    here); this record only adds the workspace/client/stage/replay context
    the kernel deliberately does not carry.
    """

    engagement_id: str
    package_id: str
    client_name: str
    stage: str  # "proposed" | "scoped" | "delivered" | "reconciled"
    economics: ServiceEconomics | None
    evidence_refs: tuple[EvidenceRef, ...] = ()
    context: WorkspaceReplayContext = field(default_factory=WorkspaceReplayContext)
    data_adequate: bool = True
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "engagement_id": self.engagement_id,
            "package_id": self.package_id,
            "client_name": self.client_name,
            "stage": self.stage,
            "economics": self.economics.to_dict() if self.economics else None,
            "evidence_refs": [item.to_dict() for item in self.evidence_refs],
            "context": self.context.to_dict(),
            "data_adequate": self.data_adequate,
            "reasons": list(self.reasons),
            "status": "data_inadequate" if not self.data_adequate else "ready_for_client_service",
        }


def launch_blockers_for_ownership(ownership: CommercialOwnership) -> tuple[str, ...]:
    """Unknown ownership must block launch readiness where material.

    Every role in ``OWNERSHIP_ROLES`` is treated as material to a launch
    decision (a merchant_of_record or support_owner that is "unknown" is not
    a safe default — it means nobody is accountable if the promise fails).
    """
    return tuple(sorted(f"unknown_{role}" for role in ownership.unknown_roles))


__all__ = [
    "EvidenceReference",
    "SupplierOfferIdentity",
    "BusinessModel",
    "OWNERSHIP_ROLES",
    "OwnershipAssignment",
    "CommercialOwnership",
    "CompetitionSnapshot",
    "PromotionGate",
    "RiskState",
    "WorkspaceReplayContext",
    "Offer",
    "ServiceEngagement",
    "launch_blockers_for_ownership",
]
