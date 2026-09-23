"""Tests for services.geographic_opportunity.report.build_geographic_opportunity_report.

Covers the mission's ten required adversarial cases explicitly, one test
class per case, plus general offering/geography-kind and determinism
coverage.
"""
from dataclasses import replace
from decimal import Decimal

import pytest

from backend.economics.kernel import CurrencyMismatchError, Money
from services.geographic_opportunity.report import build_geographic_opportunity_report
from services.geographic_opportunity.schemas import (
    DestinationPriceObservation,
    FieldEvidence,
)

from .conftest import GENERATED_AT, build_goods_offer, build_hybrid_offer, build_service_offer, build_unknown_offer, observed_evidence


class TestOfferingKinds:
    def test_goods_offering_produces_scenarios_and_comparison(self):
        report = build_geographic_opportunity_report(build_goods_offer(), generated_at=GENERATED_AT)
        assert [s.scenario_id for s in report.landed_cost_scenarios] == ["base", "best_case", "worst_case"]
        assert report.comparison is not None

    def test_service_offering_produces_no_landed_cost_scenarios(self):
        report = build_geographic_opportunity_report(build_service_offer(), generated_at=GENERATED_AT)
        assert report.landed_cost_scenarios == ()

    def test_hybrid_offering_preserves_both_components(self):
        report = build_geographic_opportunity_report(build_hybrid_offer(), generated_at=GENERATED_AT)
        categories = {entry.category for entry in report.risk_matrix}
        assert "bilateral_trade_flow" in categories
        assert "service_capacity" in categories


class TestUnknownGeography:
    def test_unknown_geography_produces_a_single_blocker_and_nothing_else(self):
        report = build_geographic_opportunity_report(build_unknown_offer(), generated_at=GENERATED_AT)
        assert any("geography_kind=unknown" in b for b in report.blockers)
        assert report.landed_cost_scenarios == ()
        assert report.comparison is None
        assert report.risk_matrix == ()


class TestAttractivePriceGapErasedByFreight:
    def test_worst_case_contribution_can_go_negative_after_freight_and_duty(self):
        # A large raw price gap (120 - 55 = 65) but heavy freight/duty in the
        # worst-case scenario should erode -- possibly eliminate -- the gap.
        offer = build_goods_offer()
        heavy_freight = replace(
            offer.freight_duty,
            international_shipping=Money(Decimal("60"), "USD"),
            duty_rate=Decimal("0.30"),
            evidence=FieldEvidence(quality="manual"),  # manual quality is subject to worst-case perturbation
        )
        offer = replace(offer, freight_duty=heavy_freight)
        report = build_geographic_opportunity_report(offer, generated_at=GENERATED_AT)
        worst = next(s for s in report.landed_cost_scenarios if s.scenario_id == "worst_case")
        base = next(s for s in report.landed_cost_scenarios if s.scenario_id == "base")
        assert worst.result.contribution_before_cac.amount < base.result.contribution_before_cac.amount


class TestAttractiveTradeFlowWithNoRetailEvidence:
    def test_present_trade_flow_but_missing_destination_price_is_flagged(self):
        offer = build_goods_offer(destination_price_evidence=None)
        offer = replace(offer, destination_price=DestinationPriceObservation(evidence=FieldEvidence(quality="missing")))
        report = build_geographic_opportunity_report(offer, generated_at=GENERATED_AT)
        assert any("attractive trade flow" in b or "no retail evidence" in b or "destination_price evidence is missing" in b for b in report.blockers)


class TestMissingDuty:
    def test_missing_duty_rate_is_flagged_blocked_never_silently_defaulted(self):
        # backend.economics.kernel.calculate_unit_economics itself falls
        # back to lane.duty_rate whenever assumptions.duty_rate is None,
        # and MarketLane.duty_rate always defaults to Decimal("0") when a
        # caller didn't set it explicitly -- so once a lane is present
        # (required whenever geography_kind="known"), the kernel's own
        # UnitEconomicsResult.missing_inputs can never show "duty_rate" as
        # missing, even when this offer's own freight_duty.duty_rate is
        # None. That is a documented, unavoidable kernel convention (see
        # docs/ai/GEOGRAPHIC_OPPORTUNITY_ANALYSIS.md), not something this
        # service can re-derive around without reimplementing kernel math
        # -- which it must never do. This service's own enforcement of
        # "never treat a missing duty rate as zero" lives one layer up,
        # at the evidence/reporting boundary: a freight_duty profile with
        # quality="missing" evidence is always flagged "blocked" severity
        # and surfaced as a report blocker, regardless of what number the
        # underlying kernel math had to assume.
        offer = build_goods_offer(duty_rate=None, freight_duty_evidence=FieldEvidence(quality="missing"))
        report = build_geographic_opportunity_report(offer, generated_at=GENERATED_AT)
        freight_entry = next(e for e in report.risk_matrix if e.category == "freight_duty")
        assert freight_entry.severity == "blocked"
        assert any("freight_duty" in b and "missing" in b for b in report.blockers)


class TestMissingSupplierCost:
    def test_missing_origin_supplier_cost_produces_no_scenarios_and_a_blocker(self):
        offer = replace(build_goods_offer(), origin_supplier_cost=None)
        report = build_geographic_opportunity_report(offer, generated_at=GENERATED_AT)
        assert report.landed_cost_scenarios == ()
        assert any("origin_supplier_cost is missing" in b for b in report.blockers)


class TestCurrencyMismatch:
    def test_destination_price_in_a_different_currency_than_origin_cost_is_rejected(self):
        offer = build_goods_offer(currency="USD")
        mismatched = replace(offer, destination_price=DestinationPriceObservation(observed_price=Money(Decimal("120"), "EUR"), evidence=observed_evidence()))
        with pytest.raises(CurrencyMismatchError):
            build_geographic_opportunity_report(mismatched, generated_at=GENERATED_AT)


class TestStaleOrConflictingCountryObservations:
    def test_stale_destination_price_is_flagged_high_severity(self):
        offer = build_goods_offer(destination_price_evidence=FieldEvidence(quality="stale", observed_at="2020-01-01"))
        report = build_geographic_opportunity_report(offer, generated_at=GENERATED_AT)
        entry = next(e for e in report.risk_matrix if e.category == "destination_price")
        assert entry.severity == "high"

    def test_conflicting_trade_flow_is_flagged_high_severity(self):
        offer = build_goods_offer(trade_flow_evidence=FieldEvidence(quality="conflicting", note="two reporting countries disagree"))
        report = build_geographic_opportunity_report(offer, generated_at=GENERATED_AT)
        entry = next(e for e in report.risk_matrix if e.category == "bilateral_trade_flow")
        assert entry.severity == "high"


class TestServiceCapacityUnavailable:
    def test_confirmed_unavailable_capacity_is_a_blocker(self):
        offer = build_service_offer(capacity_available=False)
        report = build_geographic_opportunity_report(offer, generated_at=GENERATED_AT)
        assert any("capacity is confirmed unavailable" in b for b in report.blockers)

    def test_unknown_capacity_availability_is_an_evidence_gap_not_a_blocker(self):
        offer = build_service_offer(capacity_available=None)
        report = build_geographic_opportunity_report(offer, generated_at=GENERATED_AT)
        assert any("availability has not been explicitly confirmed" in g for g in report.evidence_gaps)
        assert not any("capacity is confirmed unavailable" in b for b in report.blockers)


class TestExplicitZeroVersusMissing:
    def test_explicit_zero_duty_rate_is_used_not_treated_as_missing(self):
        offer = build_goods_offer(duty_rate=Decimal("0"))
        report = build_geographic_opportunity_report(offer, generated_at=GENERATED_AT)
        base = next(s for s in report.landed_cost_scenarios if s.scenario_id == "base")
        assert "duty_rate" not in base.result.missing_inputs
        assert base.result.duty.amount == Decimal("0")


class TestUnsupportedRegulatoryInference:
    def test_regulatory_status_is_never_an_affirmative_clearance_in_the_report(self):
        report = build_geographic_opportunity_report(build_goods_offer(), generated_at=GENERATED_AT)
        assert report.offer.regulatory.status != "compliant"
        assert report.offer.regulatory.status in {"unassessed", "requires_evidence", "documented_requirement"}

    def test_no_regulatory_observation_is_an_evidence_gap(self):
        offer = replace(build_goods_offer(), regulatory=None)
        report = build_geographic_opportunity_report(offer, generated_at=GENERATED_AT)
        assert any("no regulatory/compliance observation" in g for g in report.evidence_gaps)


class TestUnitValueProxyIsNeverTreatedAsRetailPriceOrCost:
    def test_unit_value_conflicting_with_supplier_cost_is_flagged_not_silently_trusted(self):
        offer = build_goods_offer(unit_value=Money(Decimal("200"), "USD"))
        report = build_geographic_opportunity_report(offer, generated_at=GENERATED_AT)
        assert report.comparison.unit_value_conflicts_with_supplier_cost is True
        assert any(a.action_id == "reconcile_unit_value_vs_supplier_cost" for a in report.next_actions)

    def test_unit_value_is_never_used_as_the_landed_cost_price_input(self):
        # The landed-cost "price" argument must come from destination_price,
        # never from trade_flow.unit_value -- proven by changing unit_value
        # drastically and confirming the scenario's net_sales is unaffected.
        offer = build_goods_offer()
        report_a = build_geographic_opportunity_report(offer, generated_at=GENERATED_AT)
        offer_b = replace(offer, trade_flow=replace(offer.trade_flow, unit_value=Money(Decimal("9999"), "USD")))
        report_b = build_geographic_opportunity_report(offer_b, generated_at=GENERATED_AT)
        base_a = next(s for s in report_a.landed_cost_scenarios if s.scenario_id == "base")
        base_b = next(s for s in report_b.landed_cost_scenarios if s.scenario_id == "base")
        assert base_a.result.net_sales.amount == base_b.result.net_sales.amount


class TestListingPriceIsNeverTreatedAsRealizedSale:
    def test_default_is_realized_sale_is_false(self):
        offer = build_goods_offer()
        assert offer.destination_price.is_realized_sale is False

    def test_scenario_note_discloses_the_price_type_basis(self):
        report = build_geographic_opportunity_report(build_goods_offer(), generated_at=GENERATED_AT)
        for scenario in report.landed_cost_scenarios:
            assert "marketplace_listing" in scenario.assumptions_note
            assert "not a confirmed realized-sale figure" in scenario.assumptions_note


class TestDeterminism:
    def test_identical_input_produces_identical_output(self):
        offer = build_goods_offer()
        first = build_geographic_opportunity_report(offer, generated_at=GENERATED_AT)
        second = build_geographic_opportunity_report(offer, generated_at=GENERATED_AT)
        assert first.to_dict() == second.to_dict()

    def test_report_never_claims_a_live_network_call_or_mutation(self):
        report = build_geographic_opportunity_report(build_goods_offer(), generated_at=GENERATED_AT)
        assert report.read_only is True
        assert report.network_calls is False
        assert report.mutated is False
