"""services.supplier_logistics_research.report -- deterministic evidence
report builder.

``build_supplier_logistics_report`` is the single entrypoint. It composes
``backend.economics.kernel.calculate_unit_economics`` for every landed-cost
scenario (never re-derives the math), and its risk-matrix/next-action
vocabulary is modeled after -- not copied from --
``evaluation.commerce.fulfillment_risk_lifecycle`` and
``evaluation.commerce.canonical.RiskState`` so a report produced here reads
consistently with that existing risk language.

This module performs no network I/O, contacts no supplier, and places no
order, payment, or shipment: every input is caller-supplied evidence
already captured elsewhere (see ``schemas.FieldEvidence``); this module
only assesses it.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Sequence

from backend.economics.kernel import Money, UnitEconomicsAssumptions, calculate_unit_economics
from services.status import commercial_status

from . import controls
from .schemas import (
    EVIDENCE_QUALITY,
    FieldEvidence,
    GoodsLogisticsProfile,
    LandedCostScenario,
    NextAction,
    RiskMatrixEntry,
    ServiceCapacityProfile,
    SupplierLogisticsOffer,
    SupplierLogisticsReport,
)

_SCENARIO_IDS = ("base", "best_case", "worst_case")

# Only a value whose own evidence quality is already uncertain is subject
# to sensitivity analysis; "observed" (confirmed) values never move, and a
# missing value (None) never moves either -- it stays missing in every
# scenario rather than being invented for a best/worst case.
_UNCERTAIN_QUALITIES = frozenset({"manual", "fixture"})
_PERTURBATION = Decimal("0.15")

_QUALITY_SEVERITY = {
    "observed": "low",
    "manual": "medium",
    "fixture": "medium",
    "stale": "high",
    "conflicting": "high",
    "missing": "blocked",
}


def _clamp_rate(value: Decimal) -> Decimal:
    if value < Decimal("0"):
        return Decimal("0")
    if value > Decimal("1"):
        return Decimal("1")
    return value


def _scenario_rate(value: Decimal | None, evidence_quality: str, scenario_id: str) -> Decimal | None:
    if value is None:
        return None
    if scenario_id == "base" or evidence_quality not in _UNCERTAIN_QUALITIES:
        return value
    delta = _PERTURBATION if scenario_id == "worst_case" else -_PERTURBATION
    return _clamp_rate(value * (Decimal("1") + delta))


def _build_assumptions(goods: GoodsLogisticsProfile, lane, scenario_id: str) -> UnitEconomicsAssumptions:
    customs = goods.customs
    returns_defects = goods.returns_defects
    shipping = goods.shipping

    duty_rate = _scenario_rate(customs.duty_rate, customs.evidence.quality, scenario_id)
    if duty_rate is None and lane is not None:
        duty_rate = lane.duty_rate
    tax_rate = _scenario_rate(customs.tax_rate, customs.evidence.quality, scenario_id)
    if tax_rate is None and lane is not None:
        tax_rate = lane.tax_rate

    return UnitEconomicsAssumptions(
        supplier_shipping=shipping.supplier_shipping,
        domestic_shipping=shipping.domestic_shipping,
        international_shipping=shipping.international_shipping,
        duty_rate=duty_rate,
        tax_rate=tax_rate,
        return_rate=_scenario_rate(returns_defects.return_rate, returns_defects.evidence.quality, scenario_id),
        defect_rate=_scenario_rate(returns_defects.defect_rate, returns_defects.evidence.quality, scenario_id),
        warranty_rate=_scenario_rate(returns_defects.warranty_rate, returns_defects.evidence.quality, scenario_id),
    )


def _landed_cost_scenarios(offer: SupplierLogisticsOffer, target_price: Money | None) -> tuple[LandedCostScenario, ...]:
    if offer.goods is None or offer.quoted_price is None:
        return ()
    controls.require_matching_currency(offer.quoted_price, target_price, field_name="quoted price and target price")
    price = target_price if target_price is not None else offer.quoted_price
    note = "" if target_price is not None else "cost-basis scenario: no target resale price supplied, so price equals quoted supplier cost"
    scenarios = []
    for scenario_id in _SCENARIO_IDS:
        assumptions = _build_assumptions(offer.goods, offer.lane, scenario_id)
        result = calculate_unit_economics(price, offer.quoted_price, lane=offer.lane, assumptions=assumptions, scenario=scenario_id)
        scenarios.append(LandedCostScenario(scenario_id=scenario_id, result=result, assumptions_note=note))
    return tuple(scenarios)


def _risk_entry(category: str, evidence: FieldEvidence, description: str) -> RiskMatrixEntry:
    severity = _QUALITY_SEVERITY[evidence.quality]
    # quality="observed" alone is not a verification: it is a self-reported
    # label a caller can attach to any claim, including a supplier's own
    # unconfirmed quote. controls.is_verified is the single gate for
    # whether an "observed" claim was actually backed by a human-confirmed
    # EvidenceRef in a verified-like evidence_state; an "observed" claim
    # that fails that gate is exactly as uncertain as a "manual" one and
    # must not be scored as low risk alongside genuinely verified evidence
    # -- a supplier self-claim must never become verified supplier proof
    # just by being labeled "observed".
    if evidence.quality == "observed" and not controls.is_verified(evidence):
        severity = _QUALITY_SEVERITY["manual"]
    return RiskMatrixEntry(category=category, severity=severity, description=description, evidence=evidence)


def _goods_risk_entries(goods: GoodsLogisticsProfile) -> tuple[RiskMatrixEntry, ...]:
    return (
        _risk_entry("supplier_identity", goods.supplier_evidence, "Supplier identity and quoted terms provenance"),
        _risk_entry("logistics", goods.logistics_evidence, "Fulfillment/logistics arrangement provenance"),
        _risk_entry("moq_availability", goods.moq_availability.evidence, "Minimum order quantity and stock availability"),
        _risk_entry("lead_time", goods.lead_time.evidence, "Lead time and delivery window"),
        _risk_entry("customs_duty_tax", goods.customs.evidence, "Customs, duty, and tax rate assumptions"),
        _risk_entry("shipping_cost", goods.shipping.evidence, "Shipping and landed-cost components"),
        _risk_entry("returns_defects", goods.returns_defects.evidence, "Returns and defect-rate assumptions"),
    )


def _service_risk_entries(service: ServiceCapacityProfile) -> tuple[RiskMatrixEntry, ...]:
    return (
        _risk_entry("service_capacity", service.evidence, "Provider capacity, delivery hours, and SLA/subcontractor assumptions"),
    )


def _risk_matrix(offer: SupplierLogisticsOffer) -> tuple[RiskMatrixEntry, ...]:
    entries = [_risk_entry("quoted_cost", offer.price_evidence, "Quoted cost and currency")]
    if offer.goods is not None:
        entries.extend(_goods_risk_entries(offer.goods))
    if offer.service is not None:
        entries.extend(_service_risk_entries(offer.service))
    return tuple(entries)


def _next_actions(risk_matrix: Sequence[RiskMatrixEntry]) -> tuple[NextAction, ...]:
    actions = []
    for entry in risk_matrix:
        if entry.severity not in {"high", "blocked"}:
            continue
        actions.append(
            NextAction(
                action_id=f"verify_{entry.category}",
                description=f"Verify {entry.category.replace('_', ' ')}: {entry.description}",
                blocking=entry.severity == "blocked",
                owner_hint="consulting_team",
            )
        )
    return tuple(actions)


def _blockers(offer: SupplierLogisticsOffer, risk_matrix: Sequence[RiskMatrixEntry]) -> tuple[str, ...]:
    blockers = []
    if offer.offering_kind == "unknown":
        blockers.append("offering_kind=unknown: this offering could not be classified as goods, service, or hybrid and must remain unassessed")
        return tuple(blockers)
    if offer.quoted_price is None:
        blockers.append("quoted_price is missing: no landed-cost scenario can be computed")
    for entry in risk_matrix:
        if entry.severity == "blocked":
            blockers.append(f"{entry.category}: evidence is missing")
    return tuple(blockers)


def _evidence_quality_summary(offer: SupplierLogisticsOffer, risk_matrix: Sequence[RiskMatrixEntry]) -> dict[str, int]:
    counts = Counter(entry.evidence.quality for entry in risk_matrix)
    for quality in EVIDENCE_QUALITY:
        counts.setdefault(quality, 0)
    return dict(counts)


def build_supplier_logistics_report(
    offer: SupplierLogisticsOffer,
    *,
    generated_at: str,
    target_price: Money | None = None,
) -> SupplierLogisticsReport:
    """Build a deterministic evidence report for one candidate-bound
    supplier/logistics offer. Never contacts a supplier or a live
    provider -- every input is caller-supplied evidence.

    ``target_price`` is optional and, when supplied, must share the
    offer's quoted-price currency (checked via
    ``controls.require_matching_currency``, which raises
    ``CurrencyMismatchError`` on mismatch). When omitted, landed-cost
    scenarios use the quoted supplier cost as a cost-basis-only stand-in
    for price, so contribution-margin figures read as the total added
    landed-cost burden rather than a real margin projection -- this is
    disclosed in each scenario's own ``assumptions_note``.

    An ``offering_kind="unknown"`` offer produces no landed-cost
    scenarios and no risk matrix beyond its own single blocker: it must
    remain unassessed.
    """
    if not isinstance(offer, SupplierLogisticsOffer):
        raise TypeError("offer must be a SupplierLogisticsOffer")

    if offer.offering_kind == "unknown":
        return SupplierLogisticsReport(
            candidate_id=offer.identity.candidate_id,
            offer=offer,
            landed_cost_scenarios=(),
            risk_matrix=(),
            next_actions=(),
            blockers=("offering_kind=unknown: this offering could not be classified as goods, service, or hybrid and must remain unassessed",),
            evidence_quality_summary={quality: 0 for quality in EVIDENCE_QUALITY},
            status=commercial_status(),
            generated_at=generated_at,
        )

    landed_cost_scenarios = _landed_cost_scenarios(offer, target_price)
    risk_matrix = _risk_matrix(offer)
    next_actions = _next_actions(risk_matrix)
    blockers = _blockers(offer, risk_matrix)
    evidence_quality_summary = _evidence_quality_summary(offer, risk_matrix)

    return SupplierLogisticsReport(
        candidate_id=offer.identity.candidate_id,
        offer=offer,
        landed_cost_scenarios=landed_cost_scenarios,
        risk_matrix=risk_matrix,
        next_actions=next_actions,
        blockers=blockers,
        evidence_quality_summary=evidence_quality_summary,
        status=commercial_status(),
        generated_at=generated_at,
    )
