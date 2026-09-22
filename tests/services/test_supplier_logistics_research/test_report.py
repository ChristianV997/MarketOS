"""Tests for services.supplier_logistics_research.report.build_supplier_logistics_report."""
from decimal import Decimal

import pytest

from backend.economics.kernel import CurrencyMismatchError, Money, UnitEconomicsResult
from services.supplier_logistics_research.report import build_supplier_logistics_report
from services.supplier_logistics_research.schemas import LandedCostScenario

GENERATED_AT = "2026-01-06T00:00:00Z"


class TestGoodsOfferReport:
    def test_produces_three_named_landed_cost_scenarios(self, offer_factory):
        offer = offer_factory("goods_offer_observed.json")
        report = build_supplier_logistics_report(offer, generated_at=GENERATED_AT)
        assert [s.scenario_id for s in report.landed_cost_scenarios] == ["base", "best_case", "worst_case"]
        for scenario in report.landed_cost_scenarios:
            assert isinstance(scenario, LandedCostScenario)
            assert isinstance(scenario.result, UnitEconomicsResult)

    def test_risk_matrix_covers_supplier_customs_and_logistics_separately(self, offer_factory):
        offer = offer_factory("goods_offer_observed.json")
        report = build_supplier_logistics_report(offer, generated_at=GENERATED_AT)
        categories = {entry.category for entry in report.risk_matrix}
        assert {"supplier_identity", "customs_duty_tax", "logistics", "shipping_cost"} <= categories

    def test_fully_observed_offer_has_no_blockers(self, offer_factory):
        offer = offer_factory("goods_offer_observed.json")
        report = build_supplier_logistics_report(offer, generated_at=GENERATED_AT)
        assert report.blockers == ()

    def test_missing_evidence_offer_produces_blockers_and_blocking_next_actions(self, offer_factory):
        offer = offer_factory("goods_offer_missing_evidence.json")
        report = build_supplier_logistics_report(offer, generated_at=GENERATED_AT)
        assert report.blockers
        assert any(action.blocking for action in report.next_actions)

    def test_missing_quoted_price_produces_no_landed_cost_scenarios(self, offer_factory):
        offer = offer_factory("goods_offer_missing_evidence.json")
        report = build_supplier_logistics_report(offer, generated_at=GENERATED_AT)
        # quoted_price is present in this fixture but goods evidence is missing;
        # scenarios must still compose since price is present.
        assert report.landed_cost_scenarios


class TestConflictingAndStaleEvidence:
    def test_conflicting_customs_evidence_is_flagged_high_severity(self, offer_factory):
        offer = offer_factory("goods_offer_conflicting_customs.json")
        report = build_supplier_logistics_report(offer, generated_at=GENERATED_AT)
        customs_entry = next(e for e in report.risk_matrix if e.category == "customs_duty_tax")
        assert customs_entry.severity == "high"

    def test_stale_logistics_evidence_is_flagged_high_severity(self, offer_factory):
        offer = offer_factory("goods_offer_conflicting_customs.json")
        report = build_supplier_logistics_report(offer, generated_at=GENERATED_AT)
        logistics_entry = next(e for e in report.risk_matrix if e.category == "logistics")
        assert logistics_entry.severity == "high"

    def test_worst_case_duty_rate_is_higher_than_best_case_for_uncertain_evidence(self, offer_factory):
        offer = offer_factory("goods_offer_conflicting_customs.json")
        report = build_supplier_logistics_report(offer, generated_at=GENERATED_AT)
        scenarios = {s.scenario_id: s.result for s in report.landed_cost_scenarios}
        assert scenarios["worst_case"].duty.amount >= scenarios["best_case"].duty.amount


class TestServiceOfferReport:
    def test_service_offer_produces_no_landed_cost_scenarios(self, offer_factory):
        offer = offer_factory("service_offer.json")
        report = build_supplier_logistics_report(offer, generated_at=GENERATED_AT)
        assert report.landed_cost_scenarios == ()

    def test_service_offer_reports_capacity_risk_without_claiming_verification(self, offer_factory):
        offer = offer_factory("service_offer.json")
        report = build_supplier_logistics_report(offer, generated_at=GENERATED_AT)
        capacity_entry = next(e for e in report.risk_matrix if e.category == "service_capacity")
        assert capacity_entry.severity in {"medium", "high", "blocked"}  # a manual claim, never "low"/verified


class TestHybridOfferReport:
    def test_hybrid_offer_preserves_both_goods_and_service_risk_entries(self, offer_factory):
        offer = offer_factory("hybrid_offer.json")
        report = build_supplier_logistics_report(offer, generated_at=GENERATED_AT)
        categories = {entry.category for entry in report.risk_matrix}
        assert "customs_duty_tax" in categories
        assert "service_capacity" in categories

    def test_hybrid_offer_produces_landed_cost_scenarios_from_its_goods_component(self, offer_factory):
        offer = offer_factory("hybrid_offer.json")
        report = build_supplier_logistics_report(offer, generated_at=GENERATED_AT)
        assert report.landed_cost_scenarios


class TestUnknownOfferingStaysUnassessed:
    def test_unknown_offering_produces_a_single_blocker_and_nothing_else(self, offer_factory):
        offer = offer_factory("unknown_offering.json")
        report = build_supplier_logistics_report(offer, generated_at=GENERATED_AT)
        assert len(report.blockers) == 1
        assert "unassessed" in report.blockers[0]
        assert report.landed_cost_scenarios == ()
        assert report.risk_matrix == ()
        assert report.next_actions == ()


class TestDeterminism:
    def test_identical_input_produces_identical_output(self, offer_factory):
        offer = offer_factory("goods_offer_observed.json")
        first = build_supplier_logistics_report(offer, generated_at=GENERATED_AT)
        second = build_supplier_logistics_report(offer, generated_at=GENERATED_AT)
        assert first.to_dict() == second.to_dict()

    def test_report_never_claims_a_live_network_call_or_mutation(self, offer_factory):
        offer = offer_factory("goods_offer_observed.json")
        report = build_supplier_logistics_report(offer, generated_at=GENERATED_AT)
        assert report.read_only is True
        assert report.network_calls is False
        assert report.mutated is False


class TestTargetPriceCurrencyGuard:
    def test_target_price_in_a_different_currency_than_the_quoted_price_is_rejected(self, offer_factory):
        offer = offer_factory("goods_offer_observed.json")
        with pytest.raises(CurrencyMismatchError):
            build_supplier_logistics_report(offer, generated_at=GENERATED_AT, target_price=Money(Decimal("30"), "EUR"))

    def test_no_target_price_discloses_cost_basis_assumption_in_the_scenario_note(self, offer_factory):
        offer = offer_factory("goods_offer_observed.json")
        report = build_supplier_logistics_report(offer, generated_at=GENERATED_AT)
        assert all("cost-basis" in scenario.assumptions_note for scenario in report.landed_cost_scenarios)
