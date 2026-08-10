"""Tests for the opt-in competition_evidence path wired into
backend.mvp_commerce.runner.run_commerce_mvp_slice — must never change the
default (competition_evidence=None) behavior, and must only activate
alongside use_opportunity_ranking=True."""
from __future__ import annotations

from pathlib import Path

from backend.adapters.research.competition_evidence import CompetitorOffer
from backend.events.repository import InMemoryEventRepository
from backend.mvp_commerce.competition_intelligence import MarketIntelligenceReport
from backend.mvp_commerce.runner import run_commerce_mvp_slice
from backend.mvp_commerce.supplier_evidence import SupplierEvidenceResult

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/commerce_mvp/public_signals.json"


def _offer(listing_id="l1", price=32.0):
    return CompetitorOffer(
        source="public_storefront", source_url=f"https://example.com/{listing_id}", crawl_timestamp=1_700_000_000.0,
        external_listing_id=listing_id, title="Portable Espresso Maker",
        field_status={"price": "observed", "title": "observed"}, price=price, currency="USD",
    )


def _market_report():
    return MarketIntelligenceReport(
        query="portable espresso maker", generated_at=1_700_000_000.0, offers=(_offer(),),
        observed_competitor_count=1, observed_median_price=32.0, observed_mean_price=32.0,
        observed_min_price=32.0, observed_max_price=32.0, observed_pricing_variance=0.0,
        observed_shipping_min=None, observed_shipping_max=None, observed_review_density=None,
        observed_rating_mean=None, observed_brand_diversity=None, observed_seller_diversity=None,
        observed_availability_ratio=None, market_maturity="unknown", market_saturation=0.05, confidence=0.5,
    )


def _supplier_evidence():
    return SupplierEvidenceResult(attempted=True, unit_cost=9.5, shipping_cost=2.0, source_url="https://cj.example/x")


class TestByteIdenticalDefault:
    def test_default_path_ignores_competition_evidence_entirely(self):
        baseline = run_commerce_mvp_slice(query="portable espresso maker", signal_fixture_path=FIXTURE)
        with_competition_but_no_ranking = run_commerce_mvp_slice(
            query="portable espresso maker", signal_fixture_path=FIXTURE, competition_evidence=_market_report(),
        )
        # use_opportunity_ranking=False (default) means competition_evidence
        # is never consulted -- byte-identical to the baseline.
        assert baseline.to_dict() == with_competition_but_no_ranking.to_dict()

    def test_default_path_has_no_market_opportunity_report(self):
        run = run_commerce_mvp_slice(query="portable espresso maker", signal_fixture_path=FIXTURE)
        assert "market_opportunity_report" not in run.metadata


class TestCompetitionEvidenceOptIn:
    def test_stores_market_opportunity_report_when_ranking_and_competition_both_supplied(self):
        run = run_commerce_mvp_slice(
            query="portable espresso maker", signal_fixture_path=FIXTURE, use_opportunity_ranking=True,
            supplier_evidence=_supplier_evidence(), competition_evidence=_market_report(),
        )
        assert "market_opportunity_report" in run.metadata
        report = run.metadata["market_opportunity_report"]
        assert report["observed_supplier_cost"] == 9.5
        assert report["observed_pricing"]["median"] == 32.0
        assert report["observed_margin"]["observed_gross_margin"] is not None

    def test_ranking_without_competition_evidence_still_reports_missing_evidence(self):
        # The report is always built once ranking is opted into (same
        # "always shown, never hidden" transparency rule as unavailable
        # scoring dimensions) -- without competition evidence it explicitly
        # flags "competitor_evidence" as missing rather than omitting the
        # report entirely.
        run = run_commerce_mvp_slice(
            query="portable espresso maker", signal_fixture_path=FIXTURE, use_opportunity_ranking=True,
            supplier_evidence=_supplier_evidence(),
        )
        report = run.metadata["market_opportunity_report"]
        assert "competitor_evidence" in report["missing_evidence"]
        assert report["observed_pricing"]["median"] is None

    def test_events_include_competition_intelligence_types(self):
        repository = InMemoryEventRepository()
        run_commerce_mvp_slice(
            query="portable espresso maker", signal_fixture_path=FIXTURE, use_opportunity_ranking=True,
            supplier_evidence=_supplier_evidence(), competition_evidence=_market_report(), write_repository=repository,
        )
        types = {event.event_type for event in repository.tail()}
        assert "competition_observed" in types
        assert "competition_summary_created" in types
        assert "market_pricing_computed" in types
        assert "market_intelligence_completed" in types

    def test_no_competition_events_without_competition_evidence(self):
        repository = InMemoryEventRepository()
        run_commerce_mvp_slice(
            query="portable espresso maker", signal_fixture_path=FIXTURE, use_opportunity_ranking=True,
            supplier_evidence=_supplier_evidence(), write_repository=repository,
        )
        types = {event.event_type for event in repository.tail()}
        assert "competition_summary_created" not in types

    def test_opportunity_score_dimensions_reflect_competition_evidence(self):
        run = run_commerce_mvp_slice(
            query="portable espresso maker", signal_fixture_path=FIXTURE, use_opportunity_ranking=True,
            supplier_evidence=_supplier_evidence(), competition_evidence=_market_report(),
        )
        assessment = run.metadata["opportunity_assessment"]
        top_score = next(s for s in assessment["scores"] if s["candidate_id"] == assessment["top_candidate_id"])
        dims = {d["name"]: d for d in top_score["dimensions"]}
        assert dims["market_saturation"]["is_unknown"] is False

    def test_deterministic_replay(self):
        first = run_commerce_mvp_slice(
            query="portable espresso maker", signal_fixture_path=FIXTURE, use_opportunity_ranking=True,
            supplier_evidence=_supplier_evidence(), competition_evidence=_market_report(),
        )
        second = run_commerce_mvp_slice(
            query="portable espresso maker", signal_fixture_path=FIXTURE, use_opportunity_ranking=True,
            supplier_evidence=_supplier_evidence(), competition_evidence=_market_report(),
        )
        assert first.to_dict() == second.to_dict()
