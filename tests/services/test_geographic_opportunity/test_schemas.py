"""Contract tests for services.geographic_opportunity.schemas."""
from decimal import Decimal

import pytest

from backend.economics.kernel import CurrencyMismatchError, EconomicsError, Money
from services.geographic_opportunity.schemas import (
    BilateralTradeFlowObservation,
    CandidateBoundTradeIdentity,
    FieldEvidence,
    FreightDutyAssumptions,
    GeographicOpportunityReport,
    RegulatoryComplianceObservation,
    ReturnsLeadTimeAssumptions,
    ServiceCapacityByGeography,
    TradeOpportunityOffer,
)

from .conftest import build_goods_offer, build_lane, build_service_offer, build_unknown_offer


class TestUnknownGeographyStaysUnassessed:
    def test_unknown_geography_forbids_a_lane(self):
        identity = CandidateBoundTradeIdentity("cand-x", "", "")
        with pytest.raises(EconomicsError):
            TradeOpportunityOffer(identity=identity, offering_kind="unknown", geography_kind="unknown", lane=build_lane())

    def test_unknown_geography_with_no_profiles_is_valid(self):
        offer = build_unknown_offer()
        assert offer.lane is None and offer.trade_flow is None


class TestKnownGeographyRequiresLaneIdentityToMatch:
    """lane.origin/lane.destination_country is what actually drives every
    duty/tax/currency figure calculate_unit_economics computes, while
    identity.origin_country/identity.destination_country is what a
    report's own rendering displays as this candidate's country pair.
    Without this check a caller could bind a candidate to one country pair
    while silently pricing it with a different country's lane
    assumptions -- a geographic identity mismatch."""

    def test_lane_origin_must_match_identity_origin_country(self):
        identity = CandidateBoundTradeIdentity("cand-mismatch", "CN", "MX")
        wrong_origin_lane = build_lane(origin="VN", destination="MX")
        with pytest.raises(EconomicsError, match="lane.origin must match identity.origin_country"):
            TradeOpportunityOffer(identity=identity, offering_kind="unknown", geography_kind="known", lane=wrong_origin_lane)

    def test_lane_destination_must_match_identity_destination_country(self):
        identity = CandidateBoundTradeIdentity("cand-mismatch", "CN", "MX")
        wrong_destination_lane = build_lane(origin="CN", destination="FR")
        with pytest.raises(EconomicsError, match="lane.destination_country must match identity.destination_country"):
            TradeOpportunityOffer(identity=identity, offering_kind="unknown", geography_kind="known", lane=wrong_destination_lane)

    def test_matching_lane_and_identity_is_accepted(self):
        offer = build_goods_offer()
        assert offer.lane.origin == offer.identity.origin_country
        assert offer.lane.destination_country == offer.identity.destination_country


class TestUnknownOfferingStaysUnassessed:
    def test_unknown_offering_rejects_a_trade_flow(self):
        identity = CandidateBoundTradeIdentity("cand-y", "CN", "MX")
        trade_flow = BilateralTradeFlowObservation(evidence=FieldEvidence(quality="missing"))
        with pytest.raises(EconomicsError):
            TradeOpportunityOffer(identity=identity, offering_kind="unknown", geography_kind="known", lane=build_lane(), trade_flow=trade_flow)


class TestGoodsServiceSeparation:
    def test_goods_only_offering_rejects_a_service_capacity_profile(self):
        offer = build_goods_offer()
        service_capacity = ServiceCapacityByGeography(evidence=FieldEvidence(quality="missing"))
        with pytest.raises(EconomicsError):
            TradeOpportunityOffer(
                identity=offer.identity, offering_kind="goods", geography_kind="known", lane=offer.lane,
                trade_flow=offer.trade_flow, freight_duty=offer.freight_duty, returns_lead_time=offer.returns_lead_time,
                service_capacity=service_capacity,
            )

    def test_service_only_offering_rejects_goods_profiles(self):
        service_offer = build_service_offer()
        offer_with_trade_flow = build_goods_offer()
        with pytest.raises(EconomicsError):
            TradeOpportunityOffer(
                identity=service_offer.identity, offering_kind="service", geography_kind="known", lane=service_offer.lane,
                trade_flow=offer_with_trade_flow.trade_flow, service_capacity=service_offer.service_capacity,
            )

    def test_hybrid_offering_preserves_both_components(self):
        from .conftest import build_hybrid_offer

        offer = build_hybrid_offer()
        assert offer.trade_flow is not None
        assert offer.service_capacity is not None


class TestMissingVersusExplicitZero:
    def test_none_duty_rate_stays_none(self):
        freight_duty = FreightDutyAssumptions()
        assert freight_duty.duty_rate is None

    def test_explicit_zero_duty_rate_is_preserved_not_coerced(self):
        freight_duty = FreightDutyAssumptions(duty_rate=Decimal("0"))
        assert freight_duty.duty_rate == Decimal("0")
        assert freight_duty.duty_rate is not None

    def test_lead_time_minimum_may_be_known_while_maximum_is_unknown(self):
        window = ReturnsLeadTimeAssumptions(lead_time_minimum_days=10, lead_time_maximum_days=None)
        assert window.lead_time_minimum_days == 10
        assert window.lead_time_maximum_days is None

    def test_lead_time_rejects_minimum_greater_than_maximum(self):
        with pytest.raises(EconomicsError):
            ReturnsLeadTimeAssumptions(lead_time_minimum_days=30, lead_time_maximum_days=10)


class TestRegulatoryStatusNeverAffirmative:
    @pytest.mark.parametrize("bad_status", ["compliant", "cleared", "approved", "verified"])
    def test_rejects_affirmative_clearance_values(self, bad_status):
        with pytest.raises(EconomicsError):
            RegulatoryComplianceObservation(status=bad_status)

    def test_accepts_documented_requirement(self):
        obs = RegulatoryComplianceObservation(status="documented_requirement")
        assert obs.status == "documented_requirement"


class TestCandidateBoundIdentity:
    def test_report_candidate_id_must_match_offer_identity(self):
        offer = build_goods_offer()
        with pytest.raises(EconomicsError):
            GeographicOpportunityReport(
                candidate_id="mismatched-candidate", offer=offer, landed_cost_scenarios=(), comparison=None,
                risk_matrix=(), next_actions=(), blockers=(), evidence_gaps=(), evidence_quality_summary={},
                status="ready_for_client_service", generated_at="2026-01-01T00:00:00Z",
            )

    def test_report_read_only_invariants_cannot_be_overridden(self):
        offer = build_goods_offer()
        with pytest.raises(EconomicsError):
            GeographicOpportunityReport(
                candidate_id=offer.identity.candidate_id, offer=offer, landed_cost_scenarios=(), comparison=None,
                risk_matrix=(), next_actions=(), blockers=(), evidence_gaps=(), evidence_quality_summary={},
                status="ready_for_client_service", generated_at="2026-01-01T00:00:00Z", network_calls=True,
            )


class TestLaneCurrencyAlignment:
    def test_trade_flow_rejects_mismatched_trade_value_and_unit_value_currency(self):
        with pytest.raises(CurrencyMismatchError):
            BilateralTradeFlowObservation(trade_value=Money(Decimal("100"), "USD"), unit_value=Money(Decimal("5"), "EUR"))
