"""Contract tests for services.supplier_logistics_research.schemas."""
from decimal import Decimal

import pytest

from backend.economics.kernel import CurrencyMismatchError, EconomicsError, MarketLane, Money
from evaluation.commerce.canonical import SupplierOfferIdentity
from services.supplier_logistics_research.schemas import (
    CandidateBoundSupplierIdentity,
    CustomsDutyTaxProfile,
    FieldEvidence,
    GoodsLogisticsProfile,
    LeadTimeWindow,
    MoqAvailability,
    ReturnsDefectAssumptions,
    ServiceCapacityProfile,
    ShippingCostProfile,
    SupplierLogisticsOffer,
    SupplierLogisticsReport,
)


def _identity(candidate_id="cand-x"):
    return CandidateBoundSupplierIdentity(candidate_id, SupplierOfferIdentity("sup-x", "off-x", "sku-x"))


class TestUnknownOfferingStaysUnassessed:
    def test_unknown_offering_rejects_a_goods_profile(self):
        goods = GoodsLogisticsProfile(
            moq_availability=MoqAvailability(),
            lead_time=LeadTimeWindow(),
            fulfillment_mode="unknown",
            customs=CustomsDutyTaxProfile(),
            returns_defects=ReturnsDefectAssumptions(),
            shipping=ShippingCostProfile(),
            supplier_evidence=FieldEvidence(quality="missing"),
            logistics_evidence=FieldEvidence(quality="missing"),
        )
        with pytest.raises(EconomicsError):
            SupplierLogisticsOffer(
                identity=_identity(), offering_kind="unknown", quoted_price=None,
                price_evidence=FieldEvidence(quality="missing"), goods=goods,
            )

    def test_unknown_offering_with_no_profiles_is_valid(self):
        offer = SupplierLogisticsOffer(
            identity=_identity(), offering_kind="unknown", quoted_price=None,
            price_evidence=FieldEvidence(quality="missing"),
        )
        assert offer.goods is None and offer.service is None


class TestGoodsServiceSeparation:
    def test_goods_only_offering_rejects_a_service_profile(self, offer_factory):
        goods_offer = offer_factory("goods_offer_observed.json")
        service = ServiceCapacityProfile(evidence=FieldEvidence(quality="missing"))
        with pytest.raises(EconomicsError):
            SupplierLogisticsOffer(
                identity=goods_offer.identity, offering_kind="goods", quoted_price=goods_offer.quoted_price,
                price_evidence=goods_offer.price_evidence, goods=goods_offer.goods, service=service,
            )

    def test_service_only_offering_rejects_a_goods_profile(self, offer_factory):
        service_offer = offer_factory("service_offer.json")
        goods = GoodsLogisticsProfile(
            moq_availability=MoqAvailability(), lead_time=LeadTimeWindow(), fulfillment_mode="unknown",
            customs=CustomsDutyTaxProfile(), returns_defects=ReturnsDefectAssumptions(),
            shipping=ShippingCostProfile(), supplier_evidence=FieldEvidence(quality="missing"),
            logistics_evidence=FieldEvidence(quality="missing"),
        )
        with pytest.raises(EconomicsError):
            SupplierLogisticsOffer(
                identity=service_offer.identity, offering_kind="service", quoted_price=service_offer.quoted_price,
                price_evidence=service_offer.price_evidence, goods=goods, service=service_offer.service,
            )

    def test_hybrid_offering_preserves_both_components(self, offer_factory):
        offer = offer_factory("hybrid_offer.json")
        assert offer.goods is not None
        assert offer.service is not None
        assert offer.goods.supplier_evidence is not offer.goods.logistics_evidence


class TestMissingVersusExplicitZero:
    def test_none_duty_rate_stays_none(self):
        customs = CustomsDutyTaxProfile()
        assert customs.duty_rate is None

    def test_explicit_zero_duty_rate_is_preserved_not_coerced(self):
        customs = CustomsDutyTaxProfile(duty_rate=Decimal("0"))
        assert customs.duty_rate == Decimal("0")
        assert customs.duty_rate is not None

    def test_lead_time_minimum_may_be_known_while_maximum_is_unknown(self):
        window = LeadTimeWindow(minimum_days=10, maximum_days=None)
        assert window.minimum_days == 10
        assert window.maximum_days is None

    def test_lead_time_rejects_minimum_greater_than_maximum(self):
        with pytest.raises(EconomicsError):
            LeadTimeWindow(minimum_days=30, maximum_days=10)


class TestCandidateBoundIdentity:
    def test_report_candidate_id_must_match_offer_identity(self, offer_factory):
        offer = offer_factory("goods_offer_observed.json")
        with pytest.raises(EconomicsError):
            SupplierLogisticsReport(
                candidate_id="mismatched-candidate", offer=offer, landed_cost_scenarios=(), risk_matrix=(),
                next_actions=(), blockers=(), evidence_quality_summary={}, status="ready_for_client_service",
                generated_at="2026-01-01T00:00:00Z",
            )

    def test_report_read_only_invariants_cannot_be_overridden(self, offer_factory):
        offer = offer_factory("goods_offer_observed.json")
        with pytest.raises(EconomicsError):
            SupplierLogisticsReport(
                candidate_id=offer.identity.candidate_id, offer=offer, landed_cost_scenarios=(), risk_matrix=(),
                next_actions=(), blockers=(), evidence_quality_summary={}, status="ready_for_client_service",
                generated_at="2026-01-01T00:00:00Z", network_calls=True,
            )


class TestLaneCurrencyAlignment:
    def test_offer_rejects_a_lane_whose_currency_differs_from_the_quoted_price(self):
        lane = MarketLane("lane-1", "CN", "CN", "MX", "US", currency="EUR")
        with pytest.raises(CurrencyMismatchError):
            SupplierLogisticsOffer(
                identity=_identity(), offering_kind="unknown", quoted_price=Money(Decimal("10"), "USD"),
                price_evidence=FieldEvidence(quality="missing"), lane=lane,
            )
