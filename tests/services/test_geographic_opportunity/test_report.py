"""Tests for services.geographic_opportunity.report.build_geographic_opportunity_report.

Covers the mission's ten required adversarial cases explicitly, one test
class per case, plus general offering/geography-kind and determinism
coverage.
"""
from dataclasses import replace
from decimal import Decimal

import pytest

from backend.economics.kernel import (
    CurrencyMismatchError,
    MarketLane,
    Money,
    UnitEconomicsAssumptions,
    calculate_unit_economics,
)
from services.geographic_opportunity import controls
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


class TestKernelDutyRateFallbackIsNeverReportedAsMissing:
    """Regression guard for the kernel behavior itself, distinct from
    TestMissingDuty above (which proves this SERVICE's own blocker
    workaround). This class calls
    backend.economics.kernel.calculate_unit_economics directly, with no
    services.geographic_opportunity code involved at all, to lock in the
    exact kernel convention documented in
    docs/ai/GEOGRAPHIC_OPPORTUNITY_ANALYSIS.md and report.py's own
    _build_assumptions comment: once a lane is present,
    UnitEconomicsResult.missing_inputs can never show "duty_rate" as
    missing, even when the caller's own UnitEconomicsAssumptions.duty_rate
    is None -- the kernel always falls back to lane.duty_rate, and
    MarketLane.duty_rate always defaults to Decimal("0") when unset. If a
    future kernel change altered this convention (e.g. to distinguish "the
    lane never set duty_rate" from "the lane confirms 0%"), this test
    would fail and needs to fail -- it exists specifically to catch that
    kind of silent change, not to defend the current behavior as correct.
    """

    def test_duty_rate_falls_back_silently_to_a_lane_with_an_explicit_rate(self):
        lane = MarketLane("lane-x", "CN", "CN", "MX", "MX", currency="USD", duty_rate=Decimal("0.05"), tax_rate=Decimal("0.16"))
        price = Money(Decimal("120"), "USD")
        cost = Money(Decimal("55"), "USD")
        assumptions = UnitEconomicsAssumptions(duty_rate=None)  # caller never supplied this

        result = calculate_unit_economics(price, cost, lane=lane, assumptions=assumptions, scenario="base")

        assert "duty_rate" not in result.missing_inputs
        # The kernel silently used the lane's own 5% duty_rate against the
        # landed cost (product_cost, since no shipping legs were supplied
        # here) -- proving the fallback actually fired, not just that
        # "duty_rate" happens to be absent from missing_inputs for some
        # other reason.
        assert result.duty.amount == cost.amount * Decimal("0.05")

    def test_duty_rate_falls_back_silently_to_a_lane_that_never_set_one(self):
        # MarketLane.duty_rate defaults to Decimal("0") when a caller never
        # set it explicitly -- so this lane's "0%" is indistinguishable,
        # inside the kernel, from "nobody ever confirmed a duty rate for
        # this lane". Both this test and the one above must pass with
        # "duty_rate" absent from missing_inputs, since the kernel cannot
        # tell the two cases apart.
        lane = MarketLane("lane-y", "CN", "CN", "MX", "MX", currency="USD")
        price = Money(Decimal("120"), "USD")
        cost = Money(Decimal("55"), "USD")
        assumptions = UnitEconomicsAssumptions(duty_rate=None)

        result = calculate_unit_economics(price, cost, lane=lane, assumptions=assumptions, scenario="base")

        assert "duty_rate" not in result.missing_inputs
        assert result.duty.amount == Decimal("0")

    def test_duty_rate_is_reported_missing_only_when_no_lane_is_supplied_at_all(self):
        # Without a lane, the kernel has no fallback at all -- this is the
        # one case where missing_inputs genuinely reflects a missing duty
        # rate, confirming the fallback (not some other code path) is what
        # suppresses "duty_rate" from missing_inputs in the two tests above.
        price = Money(Decimal("120"), "USD")
        cost = Money(Decimal("55"), "USD")
        assumptions = UnitEconomicsAssumptions(duty_rate=None)

        result = calculate_unit_economics(price, cost, lane=None, assumptions=assumptions, scenario="base")

        assert "duty_rate" in result.missing_inputs
        assert result.duty.amount == Decimal("0")


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

    def test_unit_value_and_supplier_cost_agreeing_within_threshold_is_not_flagged(self):
        # unit_value=52 vs origin_supplier_cost=55 is a ~5.5% relative
        # difference -- well under the 25% conflict threshold -- so this
        # must NOT be flagged, proving the threshold isn't a hair-trigger
        # that treats any nonzero difference as a conflict.
        offer = build_goods_offer(unit_value=Money(Decimal("52"), "USD"))
        report = build_geographic_opportunity_report(offer, generated_at=GENERATED_AT)
        assert report.comparison.unit_value_conflicts_with_supplier_cost is False

    def test_unit_value_is_never_used_as_the_comparisons_origin_cost_basis(self):
        # comparison.origin_cost_basis must come from origin_supplier_cost,
        # never from trade_flow.unit_value -- the two are structurally
        # separate fields on the offer, and this proves the comparison
        # builder never conflates them.
        offer = build_goods_offer(unit_value=Money(Decimal("9999"), "USD"))
        report = build_geographic_opportunity_report(offer, generated_at=GENERATED_AT)
        assert report.comparison.origin_cost_basis.amount == offer.origin_supplier_cost.amount
        assert report.comparison.origin_cost_basis.amount != Decimal("9999")

    def test_missing_supplier_cost_does_not_fall_back_to_the_unit_value_proxy(self):
        # With origin_supplier_cost=None, the comparison's origin_cost_basis
        # must stay None -- it must never silently substitute the trade
        # unit-value proxy as a stand-in cost basis.
        offer = replace(build_goods_offer(), origin_supplier_cost=None)
        report = build_geographic_opportunity_report(offer, generated_at=GENERATED_AT)
        assert report.comparison.origin_cost_basis is None
        assert report.comparison.unit_value_proxy is not None


class TestFxProvenanceIsEnforcedNotJustAvailable:
    """controls.require_fx_provenance existed as an unused utility before
    this finalization pass; report.py's _build_comparison and
    _landed_cost_scenarios now call it on every Money that could reach a
    comparison or landed-cost scenario, so a Money that already carries a
    currency conversion (exchange_rate set) without an acceptable,
    explicit rate source is rejected before a report is ever produced --
    not just theoretically rejectable by a caller who remembers to call
    the control themselves.
    """

    def test_a_destination_price_with_an_unacceptable_fx_source_is_rejected(self):
        offer = build_goods_offer()
        bad_price = Money(
            Decimal("120"), "USD", source="explicit", exchange_rate=Decimal("1.1"), exchange_rate_timestamp="2026-01-01T00:00:00Z"
        )
        offer = replace(offer, destination_price=replace(offer.destination_price, observed_price=bad_price))
        with pytest.raises(controls.FxProvenanceError):
            build_geographic_opportunity_report(offer, generated_at=GENERATED_AT)

    def test_an_origin_cost_with_an_unacceptable_fx_source_is_rejected(self):
        offer = build_goods_offer()
        bad_cost = Money(
            Decimal("55"), "USD", source="assumed", exchange_rate=Decimal("1.1"), exchange_rate_timestamp="2026-01-01T00:00:00Z"
        )
        offer = replace(offer, origin_supplier_cost=bad_cost)
        with pytest.raises(controls.FxProvenanceError):
            build_geographic_opportunity_report(offer, generated_at=GENERATED_AT)

    def test_a_money_with_no_exchange_rate_at_all_always_passes(self):
        # The common case: an unconverted, same-currency observation never
        # carries an exchange_rate, so this control is a no-op for it.
        offer = build_goods_offer()
        report = build_geographic_opportunity_report(offer, generated_at=GENERATED_AT)
        assert report.comparison is not None

    def test_a_money_with_an_acceptable_fx_source_is_allowed(self):
        offer = build_goods_offer()
        good_price = Money(
            Decimal("120"),
            "USD",
            source="central_bank_reference_rate",
            exchange_rate=Decimal("1.1"),
            exchange_rate_timestamp="2026-01-01T00:00:00Z",
        )
        offer = replace(offer, destination_price=replace(offer.destination_price, observed_price=good_price))
        report = build_geographic_opportunity_report(offer, generated_at=GENERATED_AT)
        assert report.comparison is not None


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
