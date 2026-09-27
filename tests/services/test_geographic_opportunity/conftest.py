"""Shared fixture-building helpers for services.geographic_opportunity
tests. Builds REAL dataclass objects directly (no mocks) -- this service
has no external file-import path of its own (unlike
backend.adapters.research.trade_flows, exercised separately in
test_trade_flows_adapter.py), so its own tests construct offers in code.
"""
from __future__ import annotations

from decimal import Decimal

from backend.economics.kernel import EvidenceRef, MarketLane, Money
from services.geographic_opportunity.schemas import (
    BilateralTradeFlowObservation,
    CandidateBoundTradeIdentity,
    DestinationPriceObservation,
    FieldEvidence,
    FreightDutyAssumptions,
    RegulatoryComplianceObservation,
    ReturnsLeadTimeAssumptions,
    ServiceCapacityByGeography,
    TradeOpportunityOffer,
)

GENERATED_AT = "2026-02-10T00:00:00Z"


def observed_evidence(evidence_id: str = "ev-observed") -> FieldEvidence:
    ref = EvidenceRef(evidence_id=evidence_id, source_type="manual_import", evidence_state="observed", human_confirmed=True)
    return FieldEvidence(quality="observed", evidence_ref=ref)


def build_lane(*, currency: str = "USD", origin: str = "CN", destination: str = "MX", duty_rate=Decimal("0.05"), tax_rate=Decimal("0.16")) -> MarketLane:
    return MarketLane(f"lane-{origin}-{destination}", origin, origin, destination, destination, currency=currency, duty_rate=duty_rate, tax_rate=tax_rate)


def build_goods_offer(
    *,
    candidate_id: str = "cand-goods",
    currency: str = "USD",
    destination_price_evidence: FieldEvidence | None = None,
    origin_cost: Money | None = None,
    origin_cost_evidence: FieldEvidence | None = None,
    trade_flow_evidence: FieldEvidence | None = None,
    freight_duty_evidence: FieldEvidence | None = None,
    duty_rate: Decimal | None = Decimal("0.05"),
    unit_value: Money | None = None,
    lane: MarketLane | None = None,
) -> TradeOpportunityOffer:
    identity = CandidateBoundTradeIdentity(candidate_id, "CN", "MX", "8501.10")
    trade_flow = BilateralTradeFlowObservation(
        period="2025",
        trade_value=Money(Decimal("500000"), currency),
        trade_quantity=Decimal("10000"),
        quantity_unit="units",
        unit_value=unit_value if unit_value is not None else Money(Decimal("50"), currency),
        evidence=trade_flow_evidence or observed_evidence("trade-flow"),
    )
    freight_duty = FreightDutyAssumptions(
        international_shipping=Money(Decimal("15"), currency),
        duty_rate=duty_rate,
        tax_rate=Decimal("0.16"),
        evidence=freight_duty_evidence or observed_evidence("freight-duty"),
    )
    returns_lead_time = ReturnsLeadTimeAssumptions(
        return_rate=Decimal("0.03"), lead_time_minimum_days=10, lead_time_maximum_days=25, evidence=observed_evidence("returns")
    )
    destination_price = DestinationPriceObservation(
        observed_price=Money(Decimal("120"), currency),
        price_type="marketplace_listing",
        sample_size=25,
        evidence=destination_price_evidence or observed_evidence("destination-price"),
    )
    return TradeOpportunityOffer(
        identity=identity,
        offering_kind="goods",
        geography_kind="known",
        lane=lane or build_lane(currency=currency),
        trade_flow=trade_flow,
        destination_price=destination_price,
        origin_supplier_cost=origin_cost if origin_cost is not None else Money(Decimal("55"), currency),
        origin_supplier_cost_evidence=origin_cost_evidence or observed_evidence("origin-cost"),
        freight_duty=freight_duty,
        marketplace_fee_rate=Decimal("0.08"),
        marketplace_fee_evidence=observed_evidence("marketplace-fee"),
        returns_lead_time=returns_lead_time,
        regulatory=RegulatoryComplianceObservation(status="requires_evidence", evidence=observed_evidence("regulatory")),
        captured_at="2026-01-15T00:00:00Z",
    )


def build_service_offer(*, candidate_id: str = "cand-service", currency: str = "USD", capacity_available: bool | None = None) -> TradeOpportunityOffer:
    identity = CandidateBoundTradeIdentity(candidate_id, "US", "MX")
    service_capacity = ServiceCapacityByGeography(
        geographic_coverage=("MX-CMX", "MX-JAL"),
        weekly_capacity_hours=Decimal("40"),
        capacity_available=capacity_available,
        subcontractor_dependency=True,
        sla_assumption="next-business-day response claimed by provider",
        evidence=FieldEvidence(quality="manual"),
    )
    return TradeOpportunityOffer(
        identity=identity,
        offering_kind="service",
        geography_kind="known",
        lane=build_lane(currency=currency, origin="US", destination="MX"),
        service_capacity=service_capacity,
        captured_at="2026-01-15T00:00:00Z",
    )


def build_hybrid_offer(*, candidate_id: str = "cand-hybrid", currency: str = "USD") -> TradeOpportunityOffer:
    goods_offer = build_goods_offer(candidate_id=candidate_id, currency=currency)
    service_capacity = ServiceCapacityByGeography(
        geographic_coverage=("MX-CMX",),
        weekly_capacity_hours=Decimal("20"),
        subcontractor_dependency=False,
        sla_assumption="installation within 48 hours, claimed by provider",
        evidence=FieldEvidence(quality="manual"),
    )
    return TradeOpportunityOffer(
        identity=goods_offer.identity,
        offering_kind="hybrid",
        geography_kind="known",
        lane=goods_offer.lane,
        trade_flow=goods_offer.trade_flow,
        destination_price=goods_offer.destination_price,
        origin_supplier_cost=goods_offer.origin_supplier_cost,
        origin_supplier_cost_evidence=goods_offer.origin_supplier_cost_evidence,
        freight_duty=goods_offer.freight_duty,
        marketplace_fee_rate=goods_offer.marketplace_fee_rate,
        marketplace_fee_evidence=goods_offer.marketplace_fee_evidence,
        returns_lead_time=goods_offer.returns_lead_time,
        service_capacity=service_capacity,
        regulatory=goods_offer.regulatory,
        captured_at="2026-01-15T00:00:00Z",
    )


def build_unknown_offer(*, candidate_id: str = "cand-unknown", geography_kind: str = "unknown", offering_kind: str = "unknown") -> TradeOpportunityOffer:
    identity = CandidateBoundTradeIdentity(candidate_id, "", "")
    return TradeOpportunityOffer(identity=identity, offering_kind=offering_kind, geography_kind=geography_kind)
