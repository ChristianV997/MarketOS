"""services.geographic_opportunity.report -- deterministic evidence report
builder for one cross-country trade/price-asymmetry opportunity.

``build_geographic_opportunity_report`` is the single entrypoint. It
composes ``backend.economics.kernel.calculate_unit_economics`` for every
landed-cost scenario (never re-derives the math), and its risk-matrix
vocabulary mirrors this repository's own established evidence-quality ->
severity mapping style. This module performs no network I/O (UN Comtrade
included), contacts no supplier, and places no import order: every input
is caller-supplied evidence already captured elsewhere.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import replace
from decimal import Decimal
from typing import Sequence

from backend.economics.kernel import Money, UnitEconomicsAssumptions, calculate_unit_economics
from services.status import commercial_status

from . import controls
from .schemas import (
    EVIDENCE_QUALITY,
    DestinationSourceComparison,
    FieldEvidence,
    GeographicOpportunityReport,
    LandedCostScenario,
    NextResearchAction,
    OpportunityRiskEntry,
    TradeOpportunityOffer,
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

# A unit-value proxy and a supplier's own quoted cost disagreeing by more
# than this fraction is flagged as a conflict -- customs unit-value
# statistics and a specific supplier's quote are different instruments and
# routinely diverge, so a small gap is not itself noteworthy.
_UNIT_VALUE_CONFLICT_THRESHOLD = Decimal("0.25")


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


def _build_assumptions(offer: TradeOpportunityOffer, scenario_id: str) -> UnitEconomicsAssumptions:
    freight_duty = offer.freight_duty
    returns_lead_time = offer.returns_lead_time

    # This module adds no fallback of its own to offer.lane.duty_rate/
    # tax_rate/marketplace_fee_rate -- freight_duty/marketplace_fee_rate
    # are passed through exactly as evidenced (None stays None). Note
    # that backend.economics.kernel.calculate_unit_economics itself still
    # falls back to the lane's own duty_rate/tax_rate/marketplace_fee_rate
    # internally when the assumption is None, and MarketLane always
    # defaults those to Decimal("0") when a caller didn't set them
    # explicitly -- an unavoidable kernel convention this service cannot
    # re-derive around (it must never reimplement kernel math). Because
    # of that, a scenario's own UnitEconomicsResult.missing_inputs can
    # never show "duty_rate"/"tax_rate"/"marketplace_fee_rate" as missing
    # once a lane is present. This service's own guarantee that a missing
    # rate is never silently treated as confirmed instead lives one layer
    # up, at the evidence/reporting boundary: see report.py's own
    # _risk_matrix/_blockers, which flag a "missing"-quality
    # freight_duty/marketplace_fee evidence as "blocked" severity
    # regardless of what number the underlying kernel math had to assume.
    # See docs/ai/GEOGRAPHIC_OPPORTUNITY_ANALYSIS.md for the full writeup.
    duty_rate = _scenario_rate(freight_duty.duty_rate, freight_duty.evidence.quality, scenario_id)
    tax_rate = _scenario_rate(freight_duty.tax_rate, freight_duty.evidence.quality, scenario_id)
    marketplace_fee_rate = _scenario_rate(offer.marketplace_fee_rate, offer.marketplace_fee_evidence.quality, scenario_id)
    return_rate = _scenario_rate(returns_lead_time.return_rate, returns_lead_time.evidence.quality, scenario_id)

    return UnitEconomicsAssumptions(
        supplier_shipping=freight_duty.supplier_shipping,
        international_shipping=freight_duty.international_shipping,
        domestic_shipping=freight_duty.domestic_shipping,
        duty_rate=duty_rate,
        tax_rate=tax_rate,
        marketplace_fee_rate=marketplace_fee_rate,
        return_rate=return_rate,
    )


def _landed_cost_scenarios(offer: TradeOpportunityOffer) -> tuple[LandedCostScenario, ...]:
    if offer.destination_price is None or offer.destination_price.observed_price is None:
        return ()
    if offer.origin_supplier_cost is None:
        return ()
    price = offer.destination_price.observed_price
    cost = offer.origin_supplier_cost
    controls.require_matching_currency(price, cost, field_name="destination price and origin supplier cost")
    # A Money that already carries an exchange_rate (i.e. was converted by
    # the caller before reaching this service) must name an acceptable,
    # explicit rate source -- a landed-cost scenario must never be built
    # on a currency conversion whose provenance is "assumed" or unknown.
    # A Money with no exchange_rate at all (no conversion happened) always
    # passes this check unchanged.
    controls.require_fx_provenance(price, field_name="destination_price.observed_price")
    controls.require_fx_provenance(cost, field_name="origin_supplier_cost")
    # is_realized_sale must be reflected accurately here: this note is the
    # one place a landed-cost scenario states, in plain text, whether its
    # own destination price is confirmed realized-sale evidence or only a
    # listing/quote. Stating "not a confirmed realized-sale figure"
    # unconditionally -- regardless of what the caller actually confirmed
    # -- would misrepresent genuine realized-sale evidence as unconfirmed,
    # exactly the listing-price-vs-realized-sale confusion this service
    # must not produce.
    if offer.destination_price.is_realized_sale:
        note = "based on a destination price observation of price_type={0!r}; caller has confirmed this is a realized-sale figure".format(
            offer.destination_price.price_type
        )
    else:
        note = "based on a destination price observation of price_type={0!r}; not a confirmed realized-sale figure".format(
            offer.destination_price.price_type
        )
    scenarios = []
    for scenario_id in _SCENARIO_IDS:
        assumptions = _build_assumptions(offer, scenario_id)
        result = calculate_unit_economics(price, cost, lane=offer.lane, assumptions=assumptions, scenario=scenario_id)
        scenarios.append(LandedCostScenario(scenario_id=scenario_id, result=result, assumptions_note=note))
    return tuple(scenarios)


def _build_comparison(offer: TradeOpportunityOffer) -> DestinationSourceComparison | None:
    if offer.geography_kind == "unknown":
        return None
    destination_price = offer.destination_price.observed_price if offer.destination_price is not None else None
    origin_cost = offer.origin_supplier_cost
    unit_value = offer.trade_flow.unit_value if offer.trade_flow is not None else None

    # Any Money reaching this comparison that already carries an
    # exchange_rate (a conversion the caller performed before handing it
    # to this service) must name an acceptable, explicit FX source -- see
    # controls.require_fx_provenance. A Money with no exchange_rate at
    # all always passes unchanged, so this is a no-op for the common
    # case of same-currency, unconverted observations.
    if destination_price is not None:
        controls.require_fx_provenance(destination_price, field_name="comparison.destination_price")
    if origin_cost is not None:
        controls.require_fx_provenance(origin_cost, field_name="comparison.origin_cost_basis")
    if unit_value is not None:
        controls.require_fx_provenance(unit_value, field_name="comparison.unit_value_proxy")

    notes: list[str] = []
    # A price_gap here is only ever as trustworthy as destination_price
    # itself. Unlike _landed_cost_scenarios (which already discloses this
    # in each scenario's own assumptions_note), this comparison -- and its
    # client-safe export in export.py -- previously surfaced price_gap
    # with no indication that destination_price could be an unconfirmed
    # marketplace listing rather than a realized sale. Disclosing it here
    # too closes that gap for this separate code path.
    if destination_price is not None:
        if offer.destination_price.is_realized_sale:
            notes.append(
                "destination_price is based on a destination price observation of price_type={0!r}; caller has confirmed this is a realized-sale figure".format(
                    offer.destination_price.price_type
                )
            )
        else:
            notes.append(
                "destination_price is based on a destination price observation of price_type={0!r}; not a confirmed realized-sale figure".format(
                    offer.destination_price.price_type
                )
            )
    price_gap: Money | None = None
    if destination_price is not None and origin_cost is not None:
        if destination_price.currency == origin_cost.currency:
            price_gap = destination_price - origin_cost
        else:
            notes.append("destination price and origin cost are in different currencies; gap not computed without an explicit conversion")
    elif destination_price is None:
        notes.append("no destination price observation available")
    elif origin_cost is None:
        notes.append("no origin supplier cost available")

    conflict = False
    if unit_value is not None and origin_cost is not None:
        if unit_value.currency == origin_cost.currency:
            if origin_cost.amount > Decimal("0"):
                relative_diff = abs(unit_value.amount - origin_cost.amount) / origin_cost.amount
                conflict = relative_diff > _UNIT_VALUE_CONFLICT_THRESHOLD
                if conflict:
                    notes.append("trade unit-value proxy differs from the supplier's own quoted cost by more than 25%")
        else:
            notes.append("unit-value proxy and origin cost are in different currencies; conflict not evaluated")

    if unit_value is not None:
        notes.append("unit_value_proxy is a customs statistics proxy, not a retail price and not a verified supplier quote")

    return DestinationSourceComparison(
        destination_price=destination_price,
        origin_cost_basis=origin_cost,
        price_gap=price_gap,
        unit_value_proxy=unit_value,
        unit_value_conflicts_with_supplier_cost=conflict,
        notes=tuple(notes),
    )


def _risk_entry(category: str, evidence: FieldEvidence, description: str) -> OpportunityRiskEntry:
    severity = _QUALITY_SEVERITY[evidence.quality]
    # quality="observed" alone is not a verification: it is a self-reported
    # label a caller can attach to any claim, including a supplier's own
    # unconfirmed quote. controls.is_verified is the single gate for
    # whether an "observed" claim was actually backed by a human-confirmed
    # EvidenceRef in a verified-like evidence_state; an "observed" claim
    # that fails that gate is exactly as uncertain as a "manual" one and
    # must not be scored as low risk alongside genuinely verified evidence.
    if evidence.quality == "observed" and not controls.is_verified(evidence):
        severity = _QUALITY_SEVERITY["manual"]
    return OpportunityRiskEntry(category=category, severity=severity, description=description, evidence=evidence)


def _risk_matrix(offer: TradeOpportunityOffer) -> tuple[OpportunityRiskEntry, ...]:
    entries: list[OpportunityRiskEntry] = []
    if offer.destination_price is not None:
        entries.append(_risk_entry("destination_price", offer.destination_price.evidence, "Destination price observation"))
    entries.append(_risk_entry("origin_supplier_cost", offer.origin_supplier_cost_evidence, "Origin supplier cost basis"))
    if offer.trade_flow is not None:
        entries.append(_risk_entry("bilateral_trade_flow", offer.trade_flow.evidence, "Bilateral trade-flow observation"))
    if offer.freight_duty is not None:
        entries.append(_risk_entry("freight_duty", offer.freight_duty.evidence, "Freight and duty assumptions"))
    entries.append(_risk_entry("marketplace_fee", offer.marketplace_fee_evidence, "Marketplace fee assumption"))
    if offer.returns_lead_time is not None:
        entries.append(_risk_entry("returns_lead_time", offer.returns_lead_time.evidence, "Returns and lead-time assumptions"))
    if offer.service_capacity is not None:
        entries.append(_risk_entry("service_capacity", offer.service_capacity.evidence, "Service-delivery capacity by geography"))
    if offer.regulatory is not None:
        entries.append(_risk_entry("regulatory", offer.regulatory.evidence, "Regulatory/compliance observation"))
    return tuple(entries)


def _next_actions(risk_matrix: Sequence[OpportunityRiskEntry], comparison: DestinationSourceComparison | None) -> tuple[NextResearchAction, ...]:
    actions = []
    for entry in risk_matrix:
        if entry.severity not in {"high", "blocked"}:
            continue
        actions.append(
            NextResearchAction(
                action_id=f"verify_{entry.category}",
                description=f"Verify {entry.category.replace('_', ' ')}: {entry.description}",
                blocking=entry.severity == "blocked",
                owner_hint="trade_research_team",
            )
        )
    if comparison is not None and comparison.unit_value_conflicts_with_supplier_cost:
        actions.append(
            NextResearchAction(
                action_id="reconcile_unit_value_vs_supplier_cost",
                description="Reconcile the trade unit-value proxy against the supplier's own quoted cost before relying on either.",
                blocking=False,
                owner_hint="trade_research_team",
            )
        )
    return tuple(actions)


def _blockers(offer: TradeOpportunityOffer, risk_matrix: Sequence[OpportunityRiskEntry]) -> tuple[str, ...]:
    blockers: list[str] = []
    if offer.geography_kind == "unknown":
        blockers.append("geography_kind=unknown: origin/destination could not be established and must remain unassessed")
    if offer.offering_kind == "unknown":
        blockers.append("offering_kind=unknown: this offering could not be classified as goods, service, or hybrid and must remain unassessed")
    if offer.geography_kind == "unknown" or offer.offering_kind == "unknown":
        return tuple(blockers)
    if offer.destination_price is None or offer.destination_price.observed_price is None:
        blockers.append("destination_price is missing: no landed-cost scenario can be computed")
    if offer.origin_supplier_cost is None:
        blockers.append("origin_supplier_cost is missing: no landed-cost scenario can be computed")
    if (
        offer.trade_flow is not None
        and offer.trade_flow.evidence.quality != "missing"
        and (offer.destination_price is None or offer.destination_price.evidence.quality == "missing")
    ):
        blockers.append("bilateral_trade_flow evidence is present but destination_price evidence is missing: an attractive trade flow alone is not retail evidence")
    if offer.service_capacity is not None and offer.service_capacity.capacity_available is False:
        blockers.append("service_capacity: capacity is confirmed unavailable")
    for entry in risk_matrix:
        if entry.severity == "blocked":
            blockers.append(f"{entry.category}: evidence is missing")
    return tuple(blockers)


def _evidence_gaps(offer: TradeOpportunityOffer, risk_matrix: Sequence[OpportunityRiskEntry]) -> tuple[str, ...]:
    gaps = [f"{entry.category}: evidence quality is {entry.evidence.quality}" for entry in risk_matrix if entry.evidence.quality in {"missing", "stale", "conflicting"}]
    gaps.extend(
        f"{entry.category}: evidence is labeled observed but is not verified (no human-confirmed evidence reference in a verified evidence state)"
        for entry in risk_matrix
        if entry.evidence.quality == "observed" and not controls.is_verified(entry.evidence)
    )
    if offer.service_capacity is not None and offer.service_capacity.capacity_available is None:
        gaps.append("service_capacity: availability has not been explicitly confirmed either way")
    if offer.regulatory is None and offer.geography_kind == "known":
        gaps.append("regulatory: no regulatory/compliance observation was supplied for this destination")
    return tuple(gaps)


def _evidence_quality_summary(risk_matrix: Sequence[OpportunityRiskEntry]) -> dict[str, int]:
    counts = Counter(entry.evidence.quality for entry in risk_matrix)
    for quality in EVIDENCE_QUALITY:
        counts.setdefault(quality, 0)
    return dict(counts)


def _fingerprint(report: GeographicOpportunityReport) -> str:
    """Deterministic SHA-256 over the report's own sorted-JSON payload,
    excluding ``generated_at`` and ``fingerprint`` itself, matching the
    fingerprinting convention already established by every other evidence
    service in this repository (e.g. services.market_research,
    services.market_research_evidence)."""
    payload = report.to_dict()
    payload.pop("generated_at", None)
    payload.pop("fingerprint", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _with_fingerprint(report: GeographicOpportunityReport) -> GeographicOpportunityReport:
    return replace(report, fingerprint=_fingerprint(report))


def build_geographic_opportunity_report(
    offer: TradeOpportunityOffer,
    *,
    generated_at: str,
) -> GeographicOpportunityReport:
    """Build a deterministic evidence report for one candidate-bound
    cross-country opportunity. Never contacts a live provider (UN
    Comtrade included) or places an import order -- every input is
    caller-supplied evidence.

    A ``geography_kind="unknown"`` or ``offering_kind="unknown"`` offer
    produces no landed-cost scenarios, no comparison, and no risk matrix
    beyond its own blocker(s): it must remain unassessed.
    """
    if not isinstance(offer, TradeOpportunityOffer):
        raise TypeError("offer must be a TradeOpportunityOffer")

    if offer.geography_kind == "unknown" or offer.offering_kind == "unknown":
        return _with_fingerprint(
            GeographicOpportunityReport(
                candidate_id=offer.identity.candidate_id,
                offer=offer,
                landed_cost_scenarios=(),
                comparison=None,
                risk_matrix=(),
                next_actions=(),
                blockers=_blockers(offer, ()),
                evidence_gaps=(),
                evidence_quality_summary={quality: 0 for quality in EVIDENCE_QUALITY},
                status=commercial_status(),
                generated_at=generated_at,
            )
        )

    landed_cost_scenarios = _landed_cost_scenarios(offer)
    comparison = _build_comparison(offer)
    risk_matrix = _risk_matrix(offer)
    next_actions = _next_actions(risk_matrix, comparison)
    blockers = _blockers(offer, risk_matrix)
    evidence_gaps = _evidence_gaps(offer, risk_matrix)
    evidence_quality_summary = _evidence_quality_summary(risk_matrix)

    return _with_fingerprint(
        GeographicOpportunityReport(
            candidate_id=offer.identity.candidate_id,
            offer=offer,
            landed_cost_scenarios=landed_cost_scenarios,
            comparison=comparison,
            risk_matrix=risk_matrix,
            next_actions=next_actions,
            blockers=blockers,
            evidence_gaps=evidence_gaps,
            evidence_quality_summary=evidence_quality_summary,
            status=commercial_status(),
            generated_at=generated_at,
        )
    )
