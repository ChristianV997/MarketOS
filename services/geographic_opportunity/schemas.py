"""services.geographic_opportunity.schemas -- offline, manual-first
cross-country price-asymmetry and trade-feasibility evidence contracts.

Every dataclass here composes existing canonical authorities rather than
duplicating them:
  * money, evidence identity, and market-lane assumptions are
    ``backend.economics.kernel.Money`` / ``EvidenceRef`` / ``MarketLane``,
    imported directly -- this module defines no competing money, FX, or
    lane-assumption type. FX provenance is ``Money``'s own
    ``exchange_rate``/``exchange_rate_timestamp``/``source`` fields; no
    richer FX-evidence concept exists anywhere else in this repository
    (confirmed by repo-wide search before writing this module), so none
    is invented here.
  * landed-cost math is ``backend.economics.kernel.calculate_unit_economics``
    (via ``report.py``) -- this module never re-derives a cost formula.
  * the per-field evidence-quality vocabulary, missing-vs-explicit-zero
    helpers, and goods/service/hybrid/unknown offering-kind gating below
    are modeled after (not imported from) the sibling
    ``services.supplier_logistics_research`` design -- that module is not
    reachable from this branch (it ships on a separate, unmerged PR), so
    this is a from-scratch re-declaration of the same proven pattern, not
    a shared import, matching this repository's own established
    convention of per-module duplication for this kind of boundary check
    (see e.g. ``backend/adapters/research/supplier_feasibility.py``'s own
    secret/HTML regexes, re-declared rather than centralized).

This module intentionally does not talk to any live provider (UN
Comtrade included), does not scrape, does not place an import order, and
does not move inventory or payment. Every numeric field that can be
legitimately unknown is typed ``... | None`` and defaults to ``None`` --
never to a numeric zero -- so a missing duty rate, missing freight cost,
or missing supplier cost is never silently indistinguishable from an
explicitly confirmed zero.

No canonical ISO-3166 country/region vocabulary exists anywhere in this
repository today (confirmed by repo-wide search); country identifiers
here are free-text strings, exactly matching
``backend.economics.kernel.MarketLane``'s own
``origin``/``ship_from``/``destination_country`` convention. "Unknown
geography" is modeled as an explicit, first-class state
(``geography_kind="unknown"``) rather than an empty/placeholder string,
mirroring this module's own ``offering_kind="unknown"`` gate.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from backend.economics.kernel import CurrencyMismatchError, EconomicsError, EvidenceRef, MarketLane, Money

SCHEMA = "MarketOS.GeographicOpportunity.v1"

# Per-field evidence-quality vocabulary. Deliberately distinct from (not a
# replacement for) backend.economics.kernel.EVIDENCE_STATES, which
# classifies one EvidenceRef/Money's overall evidence identity; this
# vocabulary classifies the *quality of a single reported observation*
# within this service's own report, and explicitly includes the states
# the mission requires be distinguishable: stale, missing, conflicting,
# manual, fixture, and observed.
EVIDENCE_QUALITY = frozenset({"observed", "manual", "fixture", "stale", "missing", "conflicting"})

OFFERING_KINDS = frozenset({"goods", "service", "hybrid", "unknown"})

GEOGRAPHY_KINDS = frozenset({"known", "unknown"})

PRICE_TYPES = frozenset({"unknown", "marketplace_listing", "retail_shelf", "wholesale_quote", "distributor_quote"})

# Never includes an affirmative-clearance value ("compliant", "cleared",
# "approved", ...): this service has no rules engine and must never
# produce an unsupported regulatory inference. The strongest state it can
# ever report is "documented_requirement" -- a requirement was found in
# evidence, not that the candidate satisfies it.
REGULATORY_STATUSES = frozenset({"unassessed", "requires_evidence", "documented_requirement"})

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
    """Provenance and freshness for one reported observation.

    ``quality`` is the single source of truth for whether an observation
    may be treated as verified anywhere downstream: only ``"observed"``
    paired with an ``evidence_ref`` whose own ``human_confirmed`` is True
    and whose ``evidence_state`` is ``"verified"``, ``"observed"``, or
    ``"live_readonly"`` counts as verified (see ``controls.is_verified``).
    A supplier's or reporter's own claim, recorded with
    ``quality="manual"`` or an unconfirmed ``evidence_ref``, is never
    promoted to verified by this dataclass or anything that consumes it.
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
class CandidateBoundTradeIdentity:
    """Binds one candidate to the origin/destination country pair (and,
    for goods/hybrid offerings, an HS code) it is being evaluated against.
    Country identifiers are free-text -- no canonical ISO-3166 vocabulary
    exists anywhere in this repository today (confirmed by repo-wide
    search before writing this module) -- matching
    ``backend.economics.kernel.MarketLane``'s own convention."""

    candidate_id: str
    origin_country: str
    destination_country: str
    hs_code: str = ""

    def __post_init__(self) -> None:
        _text(self.candidate_id, "candidate_id", allow_empty=False)
        _text(self.origin_country, "origin_country")
        _text(self.destination_country, "destination_country")
        _text(self.hs_code, "hs_code")

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "origin_country": self.origin_country,
            "destination_country": self.destination_country,
            "hs_code": self.hs_code,
        }


@dataclass(frozen=True)
class BilateralTradeFlowObservation:
    """One bilateral trade-flow observation (customs statistics), e.g. a
    UN Comtrade record for one origin/destination/HS-code/period. Every
    figure here is a customs-statistics quantity, never a retail price
    and never a supplier's quote -- ``unit_value`` is explicitly a
    *proxy* (``trade_value / trade_quantity``, when both are present),
    documented here as such so it is never confused with
    ``DestinationPriceObservation.observed_price`` or
    ``TradeOpportunityOffer.origin_supplier_cost`` downstream."""

    period: str = ""
    trade_value: Money | None = None
    trade_quantity: Decimal | None = None
    quantity_unit: str = ""
    unit_value: Money | None = None
    evidence: FieldEvidence = _MISSING_EVIDENCE

    def __post_init__(self) -> None:
        _text(self.period, "period")
        _text(self.quantity_unit, "quantity_unit")
        object.__setattr__(self, "trade_quantity", _optional_decimal(self.trade_quantity, "trade_quantity"))
        if self.trade_quantity is not None and self.trade_quantity < Decimal("0"):
            raise EconomicsError("invalid trade_quantity")
        for money_field in ("trade_value", "unit_value"):
            value = getattr(self, money_field)
            if value is not None and not isinstance(value, Money):
                raise EconomicsError(f"invalid {money_field}")
        if self.trade_value is not None and self.unit_value is not None and self.trade_value.currency != self.unit_value.currency:
            raise CurrencyMismatchError()
        if not isinstance(self.evidence, FieldEvidence):
            raise EconomicsError("invalid trade-flow evidence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "trade_value": self.trade_value.to_dict() if self.trade_value is not None else None,
            "trade_quantity": str(self.trade_quantity) if self.trade_quantity is not None else None,
            "quantity_unit": self.quantity_unit,
            "unit_value": self.unit_value.to_dict() if self.unit_value is not None else None,
            "evidence": self.evidence.to_dict(),
        }


@dataclass(frozen=True)
class DestinationPriceObservation:
    """One price observation for a country (used for both the
    destination market and, when comparing, the origin market).

    ``is_realized_sale`` defaults to ``False`` and must be explicitly set
    True by a caller who holds evidence of an actual completed sale --
    ``price_type="marketplace_listing"`` (a publicly visible asking
    price) is never, by itself, evidence of a realized sale."""

    observed_price: Money | None = None
    price_type: str = "unknown"
    sample_size: int | None = None
    is_realized_sale: bool = False
    evidence: FieldEvidence = _MISSING_EVIDENCE

    def __post_init__(self) -> None:
        if self.observed_price is not None and not isinstance(self.observed_price, Money):
            raise EconomicsError("invalid observed_price")
        if self.price_type not in PRICE_TYPES:
            raise EconomicsError("invalid price_type")
        object.__setattr__(self, "sample_size", _optional_int(self.sample_size, "sample_size"))
        if not isinstance(self.is_realized_sale, bool):
            raise EconomicsError("invalid is_realized_sale")
        if not isinstance(self.evidence, FieldEvidence):
            raise EconomicsError("invalid price evidence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "observed_price": self.observed_price.to_dict() if self.observed_price is not None else None,
            "price_type": self.price_type,
            "sample_size": self.sample_size,
            "is_realized_sale": self.is_realized_sale,
            "evidence": self.evidence.to_dict(),
        }


@dataclass(frozen=True)
class FreightDutyAssumptions:
    """Freight and duty assumptions for one lane, mirroring the three-tier
    shipping breakdown and duty/tax split
    ``backend.economics.kernel.UnitEconomicsAssumptions`` already accepts,
    so this profile can be handed straight to ``report.py`` without any
    reshaping. Each leg is ``None`` (unknown) unless evidence-backed."""

    supplier_shipping: Money | None = None
    international_shipping: Money | None = None
    domestic_shipping: Money | None = None
    duty_rate: Decimal | None = None
    tax_rate: Decimal | None = None
    evidence: FieldEvidence = _MISSING_EVIDENCE

    def __post_init__(self) -> None:
        for money_field in ("supplier_shipping", "international_shipping", "domestic_shipping"):
            value = getattr(self, money_field)
            if value is not None and not isinstance(value, Money):
                raise EconomicsError(f"invalid {money_field}")
        object.__setattr__(self, "duty_rate", _optional_decimal(self.duty_rate, "duty_rate"))
        object.__setattr__(self, "tax_rate", _optional_decimal(self.tax_rate, "tax_rate"))
        for rate_name in ("duty_rate", "tax_rate"):
            rate = getattr(self, rate_name)
            if rate is not None and not (Decimal("0") <= rate <= Decimal("1")):
                raise EconomicsError(f"invalid {rate_name}")
        if not isinstance(self.evidence, FieldEvidence):
            raise EconomicsError("invalid freight/duty evidence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "supplier_shipping": self.supplier_shipping.to_dict() if self.supplier_shipping is not None else None,
            "international_shipping": self.international_shipping.to_dict() if self.international_shipping is not None else None,
            "domestic_shipping": self.domestic_shipping.to_dict() if self.domestic_shipping is not None else None,
            "duty_rate": str(self.duty_rate) if self.duty_rate is not None else None,
            "tax_rate": str(self.tax_rate) if self.tax_rate is not None else None,
            "evidence": self.evidence.to_dict(),
        }


@dataclass(frozen=True)
class ReturnsLeadTimeAssumptions:
    """Return-rate and lead-time assumptions for the destination market."""

    return_rate: Decimal | None = None
    lead_time_minimum_days: int | None = None
    lead_time_maximum_days: int | None = None
    evidence: FieldEvidence = _MISSING_EVIDENCE

    def __post_init__(self) -> None:
        object.__setattr__(self, "return_rate", _optional_decimal(self.return_rate, "return_rate"))
        if self.return_rate is not None and not (Decimal("0") <= self.return_rate <= Decimal("1")):
            raise EconomicsError("invalid return_rate")
        object.__setattr__(self, "lead_time_minimum_days", _optional_int(self.lead_time_minimum_days, "lead_time_minimum_days"))
        object.__setattr__(self, "lead_time_maximum_days", _optional_int(self.lead_time_maximum_days, "lead_time_maximum_days"))
        if (
            self.lead_time_minimum_days is not None
            and self.lead_time_maximum_days is not None
            and self.lead_time_minimum_days > self.lead_time_maximum_days
        ):
            raise EconomicsError("lead time minimum exceeds maximum")
        if not isinstance(self.evidence, FieldEvidence):
            raise EconomicsError("invalid returns/lead-time evidence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "return_rate": str(self.return_rate) if self.return_rate is not None else None,
            "lead_time_minimum_days": self.lead_time_minimum_days,
            "lead_time_maximum_days": self.lead_time_maximum_days,
            "evidence": self.evidence.to_dict(),
        }


@dataclass(frozen=True)
class ServiceCapacityByGeography:
    """Provider capacity assumptions for a services offering in a given
    geography. Every field here is an assumption or a claim, never a
    verification: this module does not contact the provider, so
    ``weekly_capacity_hours``/``sla_assumption`` etc. can only ever be as
    trustworthy as the ``evidence`` attached to them (see
    ``controls.is_verified``). ``capacity_available`` is ``None``
    (unknown) unless explicitly confirmed either way -- a missing
    capacity confirmation is never treated as "available"."""

    geographic_coverage: tuple[str, ...] = ()
    weekly_capacity_hours: Decimal | None = None
    capacity_available: bool | None = None
    subcontractor_dependency: bool | None = None
    sla_assumption: str = ""
    evidence: FieldEvidence = _MISSING_EVIDENCE

    def __post_init__(self) -> None:
        if not isinstance(self.geographic_coverage, tuple) or any(not isinstance(item, str) for item in self.geographic_coverage):
            raise EconomicsError("invalid geographic coverage")
        object.__setattr__(self, "weekly_capacity_hours", _optional_decimal(self.weekly_capacity_hours, "weekly_capacity_hours"))
        if self.weekly_capacity_hours is not None and self.weekly_capacity_hours < Decimal("0"):
            raise EconomicsError("invalid weekly_capacity_hours")
        if self.capacity_available is not None and not isinstance(self.capacity_available, bool):
            raise EconomicsError("invalid capacity_available")
        if self.subcontractor_dependency is not None and not isinstance(self.subcontractor_dependency, bool):
            raise EconomicsError("invalid subcontractor_dependency")
        _text(self.sla_assumption, "sla_assumption")
        if not isinstance(self.evidence, FieldEvidence):
            raise EconomicsError("invalid service-capacity evidence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "geographic_coverage": list(self.geographic_coverage),
            "weekly_capacity_hours": str(self.weekly_capacity_hours) if self.weekly_capacity_hours is not None else None,
            "capacity_available": self.capacity_available,
            "subcontractor_dependency": self.subcontractor_dependency,
            "sla_assumption": self.sla_assumption,
            "evidence": self.evidence.to_dict(),
        }


@dataclass(frozen=True)
class RegulatoryComplianceObservation:
    """A regulatory/compliance observation for the destination country.
    ``status`` can never be an affirmative clearance value -- see
    ``REGULATORY_STATUSES``'s own docstring. This service has no legal
    rules engine; it records what evidence says a requirement *might be*,
    never that a candidate satisfies it."""

    status: str = "unassessed"
    requirement_note: str = ""
    evidence: FieldEvidence = _MISSING_EVIDENCE

    def __post_init__(self) -> None:
        if self.status not in REGULATORY_STATUSES:
            raise EconomicsError("invalid regulatory status")
        _text(self.requirement_note, "requirement_note")
        if not isinstance(self.evidence, FieldEvidence):
            raise EconomicsError("invalid regulatory evidence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "requirement_note": self.requirement_note,
            "evidence": self.evidence.to_dict(),
        }


@dataclass(frozen=True)
class TradeOpportunityOffer:
    """One candidate-bound cross-country opportunity under evaluation.

    ``geography_kind="unknown"`` means the destination/origin pairing
    could not be established -- it must stay unassessed: ``lane`` and
    every geography-scoped observation must be ``None`` in that case, and
    ``report.build_geographic_opportunity_report`` refuses to produce
    comparisons or landed-cost scenarios for it (only a single
    "unassessed" blocker), mirroring ``offering_kind="unknown"``'s own
    gate.

    ``offering_kind`` follows the same four-state vocabulary as
    ``services.supplier_logistics_research`` (goods/service/hybrid/
    unknown): goods/hybrid offerings require ``trade_flow``/
    ``freight_duty``/``returns_lead_time``; service/hybrid offerings
    require ``service_capacity``; a pure "service" offering forbids the
    physical-goods profiles and vice versa.
    """

    identity: CandidateBoundTradeIdentity
    offering_kind: str
    geography_kind: str
    lane: MarketLane | None = None
    trade_flow: BilateralTradeFlowObservation | None = None
    destination_price: DestinationPriceObservation | None = None
    source_price: DestinationPriceObservation | None = None
    origin_supplier_cost: Money | None = None
    origin_supplier_cost_evidence: FieldEvidence = _MISSING_EVIDENCE
    freight_duty: FreightDutyAssumptions | None = None
    marketplace_fee_rate: Decimal | None = None
    marketplace_fee_evidence: FieldEvidence = _MISSING_EVIDENCE
    returns_lead_time: ReturnsLeadTimeAssumptions | None = None
    service_capacity: ServiceCapacityByGeography | None = None
    regulatory: RegulatoryComplianceObservation | None = None
    captured_at: str = ""

    def __post_init__(self) -> None:
        if self.offering_kind not in OFFERING_KINDS:
            raise EconomicsError("invalid offering kind")
        if self.geography_kind not in GEOGRAPHY_KINDS:
            raise EconomicsError("invalid geography kind")
        _text(self.captured_at, "captured_at")
        object.__setattr__(self, "marketplace_fee_rate", _optional_decimal(self.marketplace_fee_rate, "marketplace_fee_rate"))
        if self.marketplace_fee_rate is not None and not (Decimal("0") <= self.marketplace_fee_rate <= Decimal("1")):
            raise EconomicsError("invalid marketplace_fee_rate")
        if not isinstance(self.marketplace_fee_evidence, FieldEvidence):
            raise EconomicsError("invalid marketplace-fee evidence")
        if not isinstance(self.origin_supplier_cost_evidence, FieldEvidence):
            raise EconomicsError("invalid origin-supplier-cost evidence")
        if self.origin_supplier_cost is not None and not isinstance(self.origin_supplier_cost, Money):
            raise EconomicsError("invalid origin_supplier_cost")

        if self.geography_kind == "unknown":
            if any(
                item is not None
                for item in (self.lane, self.trade_flow, self.destination_price, self.source_price, self.freight_duty, self.regulatory)
            ):
                raise EconomicsError("an unknown geography must remain unassessed")
        else:
            if self.lane is None:
                raise EconomicsError("geography_kind='known' requires a lane")
            if not isinstance(self.lane, MarketLane):
                raise EconomicsError("invalid lane")
            for optional_profile, expected_type in (
                (self.trade_flow, BilateralTradeFlowObservation),
                (self.destination_price, DestinationPriceObservation),
                (self.source_price, DestinationPriceObservation),
                (self.freight_duty, FreightDutyAssumptions),
                (self.regulatory, RegulatoryComplianceObservation),
            ):
                if optional_profile is not None and not isinstance(optional_profile, expected_type):
                    raise EconomicsError(f"invalid {expected_type.__name__}")

        if self.offering_kind == "unknown":
            if self.trade_flow is not None or self.freight_duty is not None or self.returns_lead_time is not None or self.service_capacity is not None:
                raise EconomicsError("an unknown offering must remain unassessed")
            return
        if self.offering_kind in {"goods", "hybrid"}:
            if self.trade_flow is None or self.freight_duty is None or self.returns_lead_time is None:
                raise EconomicsError(f"offering_kind={self.offering_kind} requires trade_flow, freight_duty, and returns_lead_time")
        if self.offering_kind in {"service", "hybrid"} and self.service_capacity is None:
            raise EconomicsError(f"offering_kind={self.offering_kind} requires a service_capacity profile")
        if self.offering_kind == "goods" and self.service_capacity is not None:
            raise EconomicsError("a goods-only offering must not carry a service_capacity profile")
        if self.offering_kind == "service" and any(item is not None for item in (self.trade_flow, self.freight_duty, self.returns_lead_time)):
            raise EconomicsError("a service-only offering must not carry goods trade-flow/freight/returns profiles")
        if self.returns_lead_time is not None and not isinstance(self.returns_lead_time, ReturnsLeadTimeAssumptions):
            raise EconomicsError("invalid returns_lead_time")
        if self.service_capacity is not None and not isinstance(self.service_capacity, ServiceCapacityByGeography):
            raise EconomicsError("invalid service_capacity")

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.to_dict(),
            "offering_kind": self.offering_kind,
            "geography_kind": self.geography_kind,
            "lane": self.lane.to_dict() if self.lane is not None else None,
            "trade_flow": self.trade_flow.to_dict() if self.trade_flow is not None else None,
            "destination_price": self.destination_price.to_dict() if self.destination_price is not None else None,
            "source_price": self.source_price.to_dict() if self.source_price is not None else None,
            "origin_supplier_cost": self.origin_supplier_cost.to_dict() if self.origin_supplier_cost is not None else None,
            "origin_supplier_cost_evidence": self.origin_supplier_cost_evidence.to_dict(),
            "freight_duty": self.freight_duty.to_dict() if self.freight_duty is not None else None,
            "marketplace_fee_rate": str(self.marketplace_fee_rate) if self.marketplace_fee_rate is not None else None,
            "marketplace_fee_evidence": self.marketplace_fee_evidence.to_dict(),
            "returns_lead_time": self.returns_lead_time.to_dict() if self.returns_lead_time is not None else None,
            "service_capacity": self.service_capacity.to_dict() if self.service_capacity is not None else None,
            "regulatory": self.regulatory.to_dict() if self.regulatory is not None else None,
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
class DestinationSourceComparison:
    """The destination/source comparison output. ``price_gap`` is a plain
    difference (destination minus origin), computed only when both sides
    share one currency (an explicit FX-provenanced ``Money`` must be
    supplied by the caller for a cross-currency comparison -- see
    ``controls.require_fx_provenance``); this dataclass never converts a
    currency itself."""

    destination_price: Money | None
    origin_cost_basis: Money | None
    price_gap: Money | None
    unit_value_proxy: Money | None
    unit_value_conflicts_with_supplier_cost: bool
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "destination_price": self.destination_price.to_dict() if self.destination_price is not None else None,
            "origin_cost_basis": self.origin_cost_basis.to_dict() if self.origin_cost_basis is not None else None,
            "price_gap": self.price_gap.to_dict() if self.price_gap is not None else None,
            "unit_value_proxy": self.unit_value_proxy.to_dict() if self.unit_value_proxy is not None else None,
            "unit_value_conflicts_with_supplier_cost": self.unit_value_conflicts_with_supplier_cost,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class OpportunityRiskEntry:
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
class NextResearchAction:
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
class GeographicOpportunityReport:
    """Deterministic top-level report. Never mutates, never calls a live
    provider (UN Comtrade included), never places an import order --
    ``read_only``/``network_calls``/``mutated`` are fixed invariants, not
    caller-configurable, matching every other read-only evidence surface
    in this repository."""

    candidate_id: str
    offer: TradeOpportunityOffer
    landed_cost_scenarios: tuple[LandedCostScenario, ...]
    comparison: DestinationSourceComparison | None
    risk_matrix: tuple[OpportunityRiskEntry, ...]
    next_actions: tuple[NextResearchAction, ...]
    blockers: tuple[str, ...]
    evidence_gaps: tuple[str, ...]
    evidence_quality_summary: dict[str, int]
    status: str
    generated_at: str
    schema: str = SCHEMA
    read_only: bool = True
    network_calls: bool = False
    mutated: bool = False

    def __post_init__(self) -> None:
        _text(self.candidate_id, "candidate_id", allow_empty=False)
        if not isinstance(self.offer, TradeOpportunityOffer):
            raise EconomicsError("invalid offer")
        if self.candidate_id != self.offer.identity.candidate_id:
            raise EconomicsError("report candidate_id must match the offer's own candidate binding")
        for item in self.landed_cost_scenarios:
            if not isinstance(item, LandedCostScenario):
                raise EconomicsError("invalid landed cost scenario")
        if self.comparison is not None and not isinstance(self.comparison, DestinationSourceComparison):
            raise EconomicsError("invalid comparison")
        for item in self.risk_matrix:
            if not isinstance(item, OpportunityRiskEntry):
                raise EconomicsError("invalid risk matrix entry")
        for item in self.next_actions:
            if not isinstance(item, NextResearchAction):
                raise EconomicsError("invalid next action")
        if not isinstance(self.blockers, tuple) or any(not isinstance(item, str) for item in self.blockers):
            raise EconomicsError("invalid blockers")
        if not isinstance(self.evidence_gaps, tuple) or any(not isinstance(item, str) for item in self.evidence_gaps):
            raise EconomicsError("invalid evidence gaps")
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
            "comparison": self.comparison.to_dict() if self.comparison is not None else None,
            "risk_matrix": [item.to_dict() for item in self.risk_matrix],
            "next_actions": [item.to_dict() for item in self.next_actions],
            "blockers": list(self.blockers),
            "evidence_gaps": list(self.evidence_gaps),
            "evidence_quality_summary": dict(self.evidence_quality_summary),
            "status": self.status,
            "generated_at": self.generated_at,
            "read_only": self.read_only,
            "network_calls": self.network_calls,
            "mutated": self.mutated,
        }
