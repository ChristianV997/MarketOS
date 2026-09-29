"""Tests for services.geographic_opportunity.serialization, including
broader real fixture-to-report integration: every fixture under
tests/fixtures/geographic_opportunity/offers/ is loaded through
serialization.offer_from_dict and driven all the way through
report.build_geographic_opportunity_report, not just constructed and
left unused.
"""
import json
from decimal import Decimal
from pathlib import Path

import pytest

from backend.economics.kernel import EconomicsError, EvidenceRef, MarketLane, Money
from services.geographic_opportunity.report import build_geographic_opportunity_report
from services.geographic_opportunity.schemas import FieldEvidence
from services.geographic_opportunity.serialization import (
    evidence_ref_from_dict,
    field_evidence_from_dict,
    lane_from_dict,
    money_from_dict,
    offer_from_dict,
)

from .conftest import GENERATED_AT

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "geographic_opportunity" / "offers"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text())


class TestMoneyFromDict:
    def test_builds_a_real_kernel_money(self):
        money = money_from_dict({"amount": "50", "currency": "USD"})
        assert isinstance(money, Money)
        assert money.amount == Decimal("50")
        assert money.currency == "USD"

    def test_none_input_returns_none(self):
        assert money_from_dict(None) is None

    def test_round_trips_moneys_own_to_dict_output(self):
        original = Money(Decimal("12.5"), "USD", evidence_state="observed")
        rebuilt = money_from_dict(original.to_dict())
        assert rebuilt.amount == original.amount
        assert rebuilt.currency == original.currency
        assert rebuilt.evidence_state == original.evidence_state

    def test_non_mapping_input_raises(self):
        with pytest.raises(EconomicsError):
            money_from_dict("not-a-dict")


class TestEvidenceRefFromDict:
    def test_builds_a_real_evidence_ref(self):
        ref = evidence_ref_from_dict({"evidence_id": "ev-1", "human_confirmed": True, "evidence_state": "observed"})
        assert isinstance(ref, EvidenceRef)
        assert ref.human_confirmed is True

    def test_none_input_returns_none(self):
        assert evidence_ref_from_dict(None) is None


class TestFieldEvidenceFromDict:
    def test_missing_input_defaults_to_quality_missing(self):
        evidence = field_evidence_from_dict(None)
        assert evidence.quality == "missing"

    def test_builds_an_observed_field_evidence_with_a_nested_ref(self):
        evidence = field_evidence_from_dict(
            {"quality": "observed", "evidence_ref": {"evidence_id": "e1", "human_confirmed": True, "evidence_state": "observed"}}
        )
        assert isinstance(evidence, FieldEvidence)
        assert evidence.quality == "observed"
        assert evidence.evidence_ref.human_confirmed is True


class TestLaneFromDict:
    def test_none_input_returns_none(self):
        assert lane_from_dict(None) is None

    def test_ship_from_and_warehouse_default_to_origin_and_destination(self):
        lane = lane_from_dict({"lane_id": "lane-1", "origin": "CN", "destination_country": "MX", "currency": "USD"})
        assert isinstance(lane, MarketLane)
        assert lane.ship_from == "CN"
        assert lane.warehouse == "MX"

    def test_duty_and_tax_rate_are_passed_through(self):
        lane = lane_from_dict({"lane_id": "lane-1", "origin": "CN", "destination_country": "MX", "duty_rate": "0.05", "tax_rate": "0.16"})
        assert lane.duty_rate == Decimal("0.05")
        assert lane.tax_rate == Decimal("0.16")

    def test_omitting_duty_rate_keeps_marketlanes_own_default(self):
        # This is the exact "explicit zero vs missing" ambiguity this
        # module documents: a lane built without duty_rate gets
        # MarketLane's own Decimal("0") default, not None -- lane_from_dict
        # never invents a value, it simply does not override the kernel's
        # own default when the field is absent from the input dict.
        lane = lane_from_dict({"lane_id": "lane-1", "origin": "CN", "destination_country": "MX"})
        assert lane.duty_rate == Decimal("0")


class TestOfferFromDictFixtureIntegration:
    """Loads each real fixture file and drives it all the way through
    build_geographic_opportunity_report -- the "broader real
    fixture-to-report integration" this finalization pass adds. Every
    fixture here is a genuine JSON file on disk, not a dict literal
    embedded in a test."""

    def test_goods_fixture_produces_landed_cost_scenarios(self):
        offer = offer_from_dict(_load_fixture("goods_offer.json"))
        assert offer.offering_kind == "goods"
        report = build_geographic_opportunity_report(offer, generated_at=GENERATED_AT)
        assert [s.scenario_id for s in report.landed_cost_scenarios] == ["base", "best_case", "worst_case"]
        assert report.comparison is not None
        assert report.candidate_id == "cand-fixture-goods"

    def test_service_fixture_produces_no_landed_cost_scenarios(self):
        offer = offer_from_dict(_load_fixture("service_offer.json"))
        assert offer.offering_kind == "service"
        report = build_geographic_opportunity_report(offer, generated_at=GENERATED_AT)
        assert report.landed_cost_scenarios == ()
        entry = next(e for e in report.risk_matrix if e.category == "service_capacity")
        assert entry.evidence.quality == "manual"

    def test_hybrid_fixture_preserves_both_goods_and_service_profiles(self):
        offer = offer_from_dict(_load_fixture("hybrid_offer.json"))
        assert offer.offering_kind == "hybrid"
        report = build_geographic_opportunity_report(offer, generated_at=GENERATED_AT)
        categories = {entry.category for entry in report.risk_matrix}
        assert "bilateral_trade_flow" in categories
        assert "service_capacity" in categories
        assert report.landed_cost_scenarios != ()

    def test_unknown_fixture_produces_a_single_blocker_and_nothing_else(self):
        offer = offer_from_dict(_load_fixture("unknown_offer.json"))
        assert offer.geography_kind == "unknown"
        assert offer.offering_kind == "unknown"
        report = build_geographic_opportunity_report(offer, generated_at=GENERATED_AT)
        assert report.landed_cost_scenarios == ()
        assert report.risk_matrix == ()
        assert any("geography_kind=unknown" in b for b in report.blockers)

    def test_loading_the_same_fixture_twice_produces_identical_reports(self):
        # Determinism must hold across the file-loading path too, not just
        # for in-code-constructed offers (see TestDeterminism in
        # test_report.py).
        first = build_geographic_opportunity_report(offer_from_dict(_load_fixture("goods_offer.json")), generated_at=GENERATED_AT)
        second = build_geographic_opportunity_report(offer_from_dict(_load_fixture("goods_offer.json")), generated_at=GENERATED_AT)
        assert first.to_dict() == second.to_dict()
