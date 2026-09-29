"""services.supplier_logistics_research.schemas -- product-agnostic supplier
and logistics evidence contracts for consulting reports.

Every dataclass here composes existing canonical authorities rather than
duplicating them:
  * money, evidence identity, and market-lane assumptions are
    ``backend.economics.kernel.Money`` / ``EvidenceRef`` / ``MarketLane``,
    imported directly -- this module defines no competing money or
    evidence-identity type.
  * landed-cost math is ``backend.economics.kernel.calculate_unit_economics``
    (via ``report.py``) -- this module never re-derives a cost formula.
  * supplier offer identity composes
    ``evaluation.commerce.canonical.SupplierOfferIdentity`` (the existing
    supplier-offer identity dataclass) with a required ``candidate_id``
    binding, since that identity alone does not carry one.
  * fulfillment-mode and risk-severity vocabularies are deliberately
    modeled after (not copied from) ``evaluation.commerce.
    fulfillment_risk_lifecycle`` and ``evaluation.commerce.canonical.
    RiskState`` so a report produced here reads consistently with that
    existing risk language, without importing its 25-state order
    lifecycle (out of scope: this module never claims to track an actual
    order through fulfillment, only to assess supplier/logistics
    *evidence* before one exists).

This module intentionally does not talk to any live provider, does not
contact a supplier, and does not place an order, a payment, or a shipment.
Every numeric field that can be legitimately unknown is typed
``... | None`` and defaults to ``None`` -- never to a numeric zero -- so a
missing figure is never silently indistinguishable from an explicitly
confirmed zero (see ``EVIDENCE_QUALITY`` and each field's own docstring).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from backend.economics.kernel import CurrencyMismatchError, EconomicsError, EvidenceRef, MarketLane, Money
from evaluation.commerce.canonical import SupplierOfferIdentity

SCHEMA = "MarketOS.SupplierLogisticsResearch.v1"

# Per-field evidence-quality vocabulary. Deliberately distinct from (not a
# replacement for) backend.economics.kernel.EVIDENCE_STATES, which
# classifies one EvidenceRef/Money's overall evidence identity; this
# vocabulary classifies the *quality of a single reported field* within
# this service's own report, and explicitly includes the states the
# mission requires be distinguishable: stale, missing, conflicting,
# manual, fixture, and observed.
EVIDENCE_QUALITY = frozenset({"observed", "manual", "fixture", "stale", "missing", "conflicting"})

OFFERING_KINDS = frozenset({"goods", "service", "hybrid", "unknown"})

AVAILABILITY_STATUSES = frozenset({"unknown", "in_stock", "limited", "backordered", "discontinued", "preorder"})

FULFILLMENT_MODES = frozenset({"unknown", "dropship", "wholesale_fba", "third_party_3pl", "direct_freight", "service_delivery"})

# Matches evaluation.commerce.canonical.RiskState.level's vocabulary so a
# risk-matrix entry produced here reads consistently with that existing
# risk language.
RISK_SEVERITIES = frozenset({"low", "medium", "high", "blocked"})


def _text(value: Any, field_name: str, *, allow_empty: bool = True) -> str:
    if not isinstance(value, str):
        raise EconomicsError(f"invalid {field_name}")
    if any(ord(ch) < 0x20 and ch not in "\t" for ch in value):
        raise EconomicsError(f"invalid {field_name}")
    if not allow_empty and not value.strip():
        raise EconomicsError(f"{field_name} is required")
    return value


def _optional_decimal(value: Decimal | int | str | float | None, field_name: str) -> Decimal | None:
    """None means "unknown" and is returned unchanged -- this is the
    missing-versus-explicit-zero boundary every optional numeric field in
    this module relies on. A caller must pass an actual ``Decimal("0")``
    (or ``0``) to record a confirmed zero; nothing here ever invents one."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise EconomicsError(f"invalid {field_name}")
    try:
        result = Decimal(str(value))
    except Exception as exc:  # noqa: BLE001 - normalize every failure the same way
        raise EconomicsError(f"invalid {field_name}") from exc
    if not result.is_finite():
        raise EconomicsError(f"invalid {field_name}")
    return result


def _optional_int(value: int | None, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise EconomicsError(f"invalid {field_name}")
    if value < 0:
        raise EconomicsError(f"invalid {field_name}")
    return value


@dataclass(frozen=True)
class FieldEvidence:
    """Provenance and freshness for one reported field.

    ``quality`` is the single source of truth for whether a field may be
    treated as verified anywhere downstream: only ``"observed"`` paired
    with an ``evidence_ref`` whose own ``human_confirmed`` is True and
    whose ``evidence_state`` is ``"verified"`` or ``"observed"`` counts as
    verified (see ``controls.is_verified``). A supplier's own claim,
    recorded with ``quality="manual"`` or an unconfirmed ``evidence_ref``,
    is never promoted to verified by this dataclass or anything that
    consumes it.
    """

    quality: str
    evidence_ref: EvidenceRef | None = None
    observed_at: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        if self.quality not in EVIDENCE_QUALITY:
            raise EconomicsError("invalid evidence quality")
        if self.evidence_ref is not None and not isinstance(self.evidence_ref, EvidenceRef):
            raise EconomicsError("invalid evidence reference")
        _text(self.observed_at, "observed_at")
        _text(self.note, "note")

    def to_dict(self) -> dict[str, Any]:
        return {
            "quality": self.quality,
            "evidence_ref": self.evidence_ref.to_dict() if self.evidence_ref is not None else None,
            "observed_at": self.observed_at,
            "note": self.note,
        }


_MISSING_EVIDENCE = FieldEvidence(quality="missing")


@dataclass(frozen=True)
class CandidateBoundSupplierIdentity:
    """Binds a supplier-offer identity to the product-research candidate it
    was evaluated for. ``SupplierOfferIdentity`` alone carries no
    candidate binding; every offer this service evaluates is scoped to
    exactly one candidate, so this wrapper makes that binding explicit and
    required rather than leaving it to caller convention."""

    candidate_id: str
    supplier_offer: SupplierOfferIdentity

    def __post_init__(self) -> None:
        _text(self.candidate_id, "candidate_id", allow_empty=False)
        if not isinstance(self.supplier_offer, SupplierOfferIdentity):
            raise EconomicsError("invalid supplier offer identity")

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "supplier_id": self.supplier_offer.supplier_id,
            "offer_id": self.supplier_offer.offer_id,
            "supplier_sku": self.supplier_offer.supplier_sku,
            "variant_id": self.supplier_offer.variant_id,
        }


@dataclass(frozen=True)
class MoqAvailability:
    """Minimum order quantity and stock availability. Both quantities are
    ``None`` (missing) unless an evidence-backed number was supplied --
    a supplier claiming "always in stock" with no evidence stays
    ``availability_status="unknown"``, never silently upgraded."""

    minimum_order_quantity: int | None = None
    available_quantity: int | None = None
    availability_status: str = "unknown"
    evidence: FieldEvidence = _MISSING_EVIDENCE

    def __post_init__(self) -> None:
        object.__setattr__(self, "minimum_order_quantity", _optional_int(self.minimum_order_quantity, "minimum_order_quantity"))
        object.__setattr__(self, "available_quantity", _optional_int(self.available_quantity, "available_quantity"))
        if self.availability_status not in AVAILABILITY_STATUSES:
            raise EconomicsError("invalid availability status")
        if not isinstance(self.evidence, FieldEvidence):
            raise EconomicsError("invalid moq/availability evidence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "minimum_order_quantity": self.minimum_order_quantity,
            "available_quantity": self.available_quantity,
            "availability_status": self.availability_status,
            "evidence": self.evidence.to_dict(),
        }


@dataclass(frozen=True)
class LeadTimeWindow:
    """Delivery lead time as an explicit [minimum_days, maximum_days]
    window. Either bound may be ``None`` (unknown) independently -- a
    known minimum with an unknown maximum is common and must not force a
    fabricated ceiling."""

    minimum_days: int | None = None
    maximum_days: int | None = None
    evidence: FieldEvidence = _MISSING_EVIDENCE

    def __post_init__(self) -> None:
        object.__setattr__(self, "minimum_days", _optional_int(self.minimum_days, "minimum_days"))
        object.__setattr__(self, "maximum_days", _optional_int(self.maximum_days, "maximum_days"))
        if self.minimum_days is not None and self.maximum_days is not None and self.minimum_days > self.maximum_days:
            raise EconomicsError("lead time minimum exceeds maximum")
        if not isinstance(self.evidence, FieldEvidence):
            raise EconomicsError("invalid lead time evidence")

    def to_dict(self) -> dict[str, Any]:
        return {"minimum_days": self.minimum_days, "maximum_days": self.maximum_days, "evidence": self.evidence.to_dict()}


@dataclass(frozen=True)
class CustomsDutyTaxProfile:
    """Customs/duty/tax figures for one offer. ``duty_rate``/``tax_rate``
    of ``None`` means unknown; ``Decimal("0")`` means an evidence-backed
    confirmation that the rate is actually zero (e.g. a duty-free HS code)
    -- the two are never conflated. This is supplier-and-logistics-adjacent
    proof, kept separate from supplier proof and logistics proof (see
    ``GoodsLogisticsProfile``'s own docstring)."""

    duty_rate: Decimal | None = None
    tax_rate: Decimal | None = None
    hs_code: str = ""
    customs_notes: tuple[str, ...] = ()
    evidence: FieldEvidence = _MISSING_EVIDENCE

    def __post_init__(self) -> None:
        object.__setattr__(self, "duty_rate", _optional_decimal(self.duty_rate, "duty_rate"))
        object.__setattr__(self, "tax_rate", _optional_decimal(self.tax_rate, "tax_rate"))
        for rate_name in ("duty_rate", "tax_rate"):
            rate = getattr(self, rate_name)
            if rate is not None and not (Decimal("0") <= rate <= Decimal("1")):
                raise EconomicsError(f"invalid {rate_name}")
        _text(self.hs_code, "hs_code")
        if not isinstance(self.customs_notes, tuple) or any(not isinstance(item, str) for item in self.customs_notes):
            raise EconomicsError("invalid customs notes")
        if not isinstance(self.evidence, FieldEvidence):
            raise EconomicsError("invalid customs evidence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "duty_rate": str(self.duty_rate) if self.duty_rate is not None else None,
            "tax_rate": str(self.tax_rate) if self.tax_rate is not None else None,
            "hs_code": self.hs_code,
            "customs_notes": list(self.customs_notes),
            "evidence": self.evidence.to_dict(),
        }


@dataclass(frozen=True)
class ReturnsDefectAssumptions:
    """Return-rate and defect-rate assumptions. Both ``None`` by default
    (unknown); a target-margin or landed-cost scenario that relies on
    either must show it came from an explicit assumption, not a default."""

    return_rate: Decimal | None = None
    defect_rate: Decimal | None = None
    warranty_rate: Decimal | None = None
    evidence: FieldEvidence = _MISSING_EVIDENCE

    def __post_init__(self) -> None:
        for rate_name in ("return_rate", "defect_rate", "warranty_rate"):
            value = _optional_decimal(getattr(self, rate_name), rate_name)
            if value is not None and not (Decimal("0") <= value <= Decimal("1")):
                raise EconomicsError(f"invalid {rate_name}")
            object.__setattr__(self, rate_name, value)
        if not isinstance(self.evidence, FieldEvidence):
            raise EconomicsError("invalid returns/defect evidence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "return_rate": str(self.return_rate) if self.return_rate is not None else None,
            "defect_rate": str(self.defect_rate) if self.defect_rate is not None else None,
            "warranty_rate": str(self.warranty_rate) if self.warranty_rate is not None else None,
            "evidence": self.evidence.to_dict(),
        }


@dataclass(frozen=True)
class ShippingCostProfile:
    """Shipping-cost components, mirroring the three-tier breakdown
    ``backend.economics.kernel.UnitEconomicsAssumptions`` already accepts
    (``supplier_shipping``/``domestic_shipping``/``international_shipping``)
    so this profile can be handed straight to ``report.py`` without any
    reshaping. Each leg is ``None`` (unknown) unless evidence-backed."""

    supplier_shipping: Money | None = None
    domestic_shipping: Money | None = None
    international_shipping: Money | None = None
    evidence: FieldEvidence = _MISSING_EVIDENCE

    def __post_init__(self) -> None:
        for name in ("supplier_shipping", "domestic_shipping", "international_shipping"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, Money):
                raise EconomicsError(f"invalid {name}")
        if not isinstance(self.evidence, FieldEvidence):
            raise EconomicsError("invalid shipping evidence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "supplier_shipping": self.supplier_shipping.to_dict() if self.supplier_shipping is not None else None,
            "domestic_shipping": self.domestic_shipping.to_dict() if self.domestic_shipping is not None else None,
            "international_shipping": self.international_shipping.to_dict() if self.international_shipping is not None else None,
            "evidence": self.evidence.to_dict(),
        }


@dataclass(frozen=True)
class GoodsLogisticsProfile:
    """Physical-goods supplier/logistics profile. Supplier proof (identity
    and quoted terms), customs proof, and logistics proof are kept as
    three separate ``FieldEvidence`` records rather than one blended
    "evidence" field, so a report can show e.g. "supplier identity
    observed, customs rate missing, shipping cost manual claim" instead of
    one score that would hide which specific proof is actually missing."""

    moq_availability: MoqAvailability
    lead_time: LeadTimeWindow
    fulfillment_mode: str
    customs: CustomsDutyTaxProfile
    returns_defects: ReturnsDefectAssumptions
    shipping: ShippingCostProfile
    supplier_evidence: FieldEvidence
    logistics_evidence: FieldEvidence

    def __post_init__(self) -> None:
        if not isinstance(self.moq_availability, MoqAvailability):
            raise EconomicsError("invalid moq/availability")
        if not isinstance(self.lead_time, LeadTimeWindow):
            raise EconomicsError("invalid lead time")
        if self.fulfillment_mode not in FULFILLMENT_MODES:
            raise EconomicsError("invalid fulfillment mode")
        if not isinstance(self.customs, CustomsDutyTaxProfile):
            raise EconomicsError("invalid customs profile")
        if not isinstance(self.returns_defects, ReturnsDefectAssumptions):
            raise EconomicsError("invalid returns/defect assumptions")
        if not isinstance(self.shipping, ShippingCostProfile):
            raise EconomicsError("invalid shipping profile")
        for evidence in (self.supplier_evidence, self.logistics_evidence):
            if not isinstance(evidence, FieldEvidence):
                raise EconomicsError("invalid goods evidence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "moq_availability": self.moq_availability.to_dict(),
            "lead_time": self.lead_time.to_dict(),
            "fulfillment_mode": self.fulfillment_mode,
            "customs": self.customs.to_dict(),
            "returns_defects": self.returns_defects.to_dict(),
            "shipping": self.shipping.to_dict(),
            "supplier_evidence": self.supplier_evidence.to_dict(),
            "logistics_evidence": self.logistics_evidence.to_dict(),
        }


@dataclass(frozen=True)
class ServiceCapacityProfile:
    """Provider capacity assumptions for a services offering. Every field
    here is an assumption or a claim, never a verification: this module
    does not contact the provider, so ``sla_assumption``/
    ``subcontractor_dependency`` etc. can only ever be as trustworthy as
    the ``evidence`` attached to them (see ``controls.is_verified``)."""

    weekly_capacity_hours: Decimal | None = None
    delivery_hours_per_unit: Decimal | None = None
    business_hours: str = ""
    subcontractor_dependency: bool | None = None
    subcontractor_notes: str = ""
    sla_assumption: str = ""
    geographic_coverage: tuple[str, ...] = ()
    evidence: FieldEvidence = _MISSING_EVIDENCE

    def __post_init__(self) -> None:
        object.__setattr__(self, "weekly_capacity_hours", _optional_decimal(self.weekly_capacity_hours, "weekly_capacity_hours"))
        object.__setattr__(self, "delivery_hours_per_unit", _optional_decimal(self.delivery_hours_per_unit, "delivery_hours_per_unit"))
        for name in ("weekly_capacity_hours", "delivery_hours_per_unit"):
            value = getattr(self, name)
            if value is not None and value < Decimal("0"):
                raise EconomicsError(f"invalid {name}")
        _text(self.business_hours, "business_hours")
        if self.subcontractor_dependency is not None and not isinstance(self.subcontractor_dependency, bool):
            raise EconomicsError("invalid subcontractor_dependency")
        _text(self.subcontractor_notes, "subcontractor_notes")
        _text(self.sla_assumption, "sla_assumption")
        if not isinstance(self.geographic_coverage, tuple) or any(not isinstance(item, str) for item in self.geographic_coverage):
            raise EconomicsError("invalid geographic coverage")
        if not isinstance(self.evidence, FieldEvidence):
            raise EconomicsError("invalid service capacity evidence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "weekly_capacity_hours": str(self.weekly_capacity_hours) if self.weekly_capacity_hours is not None else None,
            "delivery_hours_per_unit": str(self.delivery_hours_per_unit) if self.delivery_hours_per_unit is not None else None,
            "business_hours": self.business_hours,
            "subcontractor_dependency": self.subcontractor_dependency,
            "subcontractor_notes": self.subcontractor_notes,
            "sla_assumption": self.sla_assumption,
            "geographic_coverage": list(self.geographic_coverage),
            "evidence": self.evidence.to_dict(),
        }


@dataclass(frozen=True)
class SupplierLogisticsOffer:
    """One candidate-bound supplier/logistics offer under evaluation.

    ``offering_kind="unknown"`` means the offering could not be classified
    as goods, a service, or a hybrid of both -- it must stay unassessed:
    both ``goods`` and ``service`` are required to be ``None`` in that
    case, and ``report.build_supplier_logistics_report`` refuses to
    produce landed-cost scenarios or a risk matrix for it (only a single
    "unassessed" blocker).
    """

    identity: CandidateBoundSupplierIdentity
    offering_kind: str
    quoted_price: Money | None
    price_evidence: FieldEvidence
    goods: GoodsLogisticsProfile | None = None
    service: ServiceCapacityProfile | None = None
    lane: MarketLane | None = None
    captured_at: str = ""

    def __post_init__(self) -> None:
        if self.offering_kind not in OFFERING_KINDS:
            raise EconomicsError("invalid offering kind")
        if self.quoted_price is not None and not isinstance(self.quoted_price, Money):
            raise EconomicsError("invalid quoted price")
        if not isinstance(self.price_evidence, FieldEvidence):
            raise EconomicsError("invalid price evidence")
        if self.lane is not None and not isinstance(self.lane, MarketLane):
            raise EconomicsError("invalid market lane")
        if self.lane is not None and self.quoted_price is not None and self.lane.currency != self.quoted_price.currency:
            raise CurrencyMismatchError()
        _text(self.captured_at, "captured_at")

        if self.offering_kind == "unknown":
            if self.goods is not None or self.service is not None:
                raise EconomicsError("an unknown offering must remain unassessed")
            return
        if self.offering_kind in {"goods", "hybrid"} and self.goods is None:
            raise EconomicsError(f"offering_kind={self.offering_kind} requires a goods profile")
        if self.offering_kind in {"service", "hybrid"} and self.service is None:
            raise EconomicsError(f"offering_kind={self.offering_kind} requires a service profile")
        if self.offering_kind == "goods" and self.service is not None:
            raise EconomicsError("a goods-only offering must not carry a service profile")
        if self.offering_kind == "service" and self.goods is not None:
            raise EconomicsError("a service-only offering must not carry a goods profile")
        if self.goods is not None and not isinstance(self.goods, GoodsLogisticsProfile):
            raise EconomicsError("invalid goods profile")
        if self.service is not None and not isinstance(self.service, ServiceCapacityProfile):
            raise EconomicsError("invalid service profile")

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.to_dict(),
            "offering_kind": self.offering_kind,
            "quoted_price": self.quoted_price.to_dict() if self.quoted_price is not None else None,
            "price_evidence": self.price_evidence.to_dict(),
            "goods": self.goods.to_dict() if self.goods is not None else None,
            "service": self.service.to_dict() if self.service is not None else None,
            "lane": self.lane.to_dict() if self.lane is not None else None,
            "captured_at": self.captured_at,
        }


@dataclass(frozen=True)
class LandedCostScenario:
    """One named landed-cost scenario. ``result`` is
    ``backend.economics.kernel.UnitEconomicsResult`` unchanged -- this
    dataclass names and annotates a scenario, it never recomputes one."""

    scenario_id: str
    result: Any  # backend.economics.kernel.UnitEconomicsResult; typed Any to avoid a hard import cycle at module load
    assumptions_note: str = ""

    def __post_init__(self) -> None:
        _text(self.scenario_id, "scenario_id", allow_empty=False)
        _text(self.assumptions_note, "assumptions_note")

    def to_dict(self) -> dict[str, Any]:
        return {"scenario_id": self.scenario_id, "result": self.result.to_dict(), "assumptions_note": self.assumptions_note}


@dataclass(frozen=True)
class RiskMatrixEntry:
    category: str
    severity: str
    description: str
    evidence: FieldEvidence

    def __post_init__(self) -> None:
        _text(self.category, "category", allow_empty=False)
        if self.severity not in RISK_SEVERITIES:
            raise EconomicsError("invalid risk severity")
        _text(self.description, "description", allow_empty=False)
        if not isinstance(self.evidence, FieldEvidence):
            raise EconomicsError("invalid risk evidence")

    def to_dict(self) -> dict[str, Any]:
        return {"category": self.category, "severity": self.severity, "description": self.description, "evidence": self.evidence.to_dict()}


@dataclass(frozen=True)
class NextAction:
    action_id: str
    description: str
    blocking: bool
    owner_hint: str = ""

    def __post_init__(self) -> None:
        _text(self.action_id, "action_id", allow_empty=False)
        _text(self.description, "description", allow_empty=False)
        if not isinstance(self.blocking, bool):
            raise EconomicsError("invalid blocking flag")
        _text(self.owner_hint, "owner_hint")

    def to_dict(self) -> dict[str, Any]:
        return {"action_id": self.action_id, "description": self.description, "blocking": self.blocking, "owner_hint": self.owner_hint}


@dataclass(frozen=True)
class SupplierLogisticsReport:
    """Deterministic top-level report. Never mutates, never calls a live
    provider, never contacts a supplier -- ``read_only``/``network_calls``/
    ``mutated`` are fixed invariants, not caller-configurable, matching
    every other read-only evidence surface in this repository."""

    candidate_id: str
    offer: SupplierLogisticsOffer
    landed_cost_scenarios: tuple[LandedCostScenario, ...]
    risk_matrix: tuple[RiskMatrixEntry, ...]
    next_actions: tuple[NextAction, ...]
    blockers: tuple[str, ...]
    evidence_quality_summary: dict[str, int]
    status: str
    generated_at: str
    schema: str = SCHEMA
    read_only: bool = True
    network_calls: bool = False
    mutated: bool = False

    def __post_init__(self) -> None:
        _text(self.candidate_id, "candidate_id", allow_empty=False)
        if not isinstance(self.offer, SupplierLogisticsOffer):
            raise EconomicsError("invalid offer")
        if self.candidate_id != self.offer.identity.candidate_id:
            raise EconomicsError("report candidate_id must match the offer's own candidate binding")
        for item in self.landed_cost_scenarios:
            if not isinstance(item, LandedCostScenario):
                raise EconomicsError("invalid landed cost scenario")
        for item in self.risk_matrix:
            if not isinstance(item, RiskMatrixEntry):
                raise EconomicsError("invalid risk matrix entry")
        for item in self.next_actions:
            if not isinstance(item, NextAction):
                raise EconomicsError("invalid next action")
        if not isinstance(self.blockers, tuple) or any(not isinstance(item, str) for item in self.blockers):
            raise EconomicsError("invalid blockers")
        if not isinstance(self.evidence_quality_summary, dict) or any(
            key not in EVIDENCE_QUALITY or not isinstance(value, int) for key, value in self.evidence_quality_summary.items()
        ):
            raise EconomicsError("invalid evidence quality summary")
        _text(self.status, "status", allow_empty=False)
        _text(self.generated_at, "generated_at", allow_empty=False)
        if self.read_only is not True or self.network_calls is not False or self.mutated is not False:
            raise EconomicsError("this service is read-only and must never mutate or call a live network")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "candidate_id": self.candidate_id,
            "offer": self.offer.to_dict(),
            "landed_cost_scenarios": [item.to_dict() for item in self.landed_cost_scenarios],
            "risk_matrix": [item.to_dict() for item in self.risk_matrix],
            "next_actions": [item.to_dict() for item in self.next_actions],
            "blockers": list(self.blockers),
            "evidence_quality_summary": dict(self.evidence_quality_summary),
            "status": self.status,
            "generated_at": self.generated_at,
            "read_only": self.read_only,
            "network_calls": self.network_calls,
            "mutated": self.mutated,
        }
