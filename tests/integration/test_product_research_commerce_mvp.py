"""Tests for the opt-in research_portfolio path wired into
backend.mvp_commerce.runner.run_commerce_mvp_slice — "Commerce MVP should
consume the Research Portfolio instead of isolated candidates when
available", but only when explicitly supplied; the default path stays
byte-identical."""
from __future__ import annotations

from pathlib import Path

from backend.adapters.research.competition_evidence import CompetitorOffer
from backend.mvp_commerce.competition_intelligence import MarketIntelligenceReport
from backend.mvp_commerce.opportunity import build_opportunity_candidates_from_signals
from backend.mvp_commerce.opportunity_scoring import score_opportunity
from backend.mvp_commerce.product_research import ResearchCandidate, build_research_portfolio
from backend.mvp_commerce.runner import _load_signals, run_commerce_mvp_slice
from backend.mvp_commerce.supplier_evidence import SupplierEvidenceResult

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/commerce_mvp/public_signals.json"


def _strong_evidence():
    supplier = SupplierEvidenceResult(attempted=True, unit_cost=9.5, shipping_cost=2.0, source_url="https://cj.example/x")
    offer = CompetitorOffer(
        source="public_storefront", source_url="https://example.com/x", crawl_timestamp=1_700_000_000.0,
        external_listing_id="l1", title="Portable Espresso Maker", field_status={"price": "observed"}, price=32.0, currency="USD",
    )
    competition = MarketIntelligenceReport(
        query="portable espresso maker", generated_at=1_700_000_000.0, offers=(offer,), observed_competitor_count=1,
        observed_median_price=32.0, observed_mean_price=32.0, observed_min_price=32.0, observed_max_price=32.0,
        observed_pricing_variance=0.0, observed_shipping_min=None, observed_shipping_max=None, observed_review_density=None,
        observed_rating_mean=None, observed_brand_diversity=None, observed_seller_diversity=None, observed_availability_ratio=None,
        market_maturity="unknown", market_saturation=0.05, confidence=0.9,
    )
    return supplier, competition


def _portfolio_for_fixture(*, force_top_id: str | None = None, with_strong_evidence_for: str | None = None):
    rows = _load_signals(FIXTURE)
    candidates = build_opportunity_candidates_from_signals(rows, "commerce-mvp-dry-run", "portable espresso maker", 5)
    supplier, competition = _strong_evidence()
    scores = {}
    for candidate in candidates:
        if with_strong_evidence_for == candidate.candidate_id:
            scores[candidate.candidate_id] = score_opportunity(candidate, supplier_evidence=supplier, competition_evidence=competition)
        else:
            scores[candidate.candidate_id] = score_opportunity(candidate)
    research_candidates = [ResearchCandidate(c.candidate_id, c, scores[c.candidate_id]) for c in candidates]
    portfolio = build_research_portfolio(research_candidates, workspace_id="commerce-mvp-dry-run", query="portable espresso maker", generated_at=1_700_000_000.0)
    if force_top_id and force_top_id in {c.candidate_id for c in candidates}:
        import dataclasses
        portfolio = dataclasses.replace(portfolio, top_candidate_id=force_top_id)
    return portfolio, candidates


class TestByteIdenticalDefault:
    def test_default_path_ignores_research_portfolio_entirely_when_none(self):
        baseline = run_commerce_mvp_slice(query="portable espresso maker", signal_fixture_path=FIXTURE)
        explicit_none = run_commerce_mvp_slice(query="portable espresso maker", signal_fixture_path=FIXTURE, research_portfolio=None)
        assert baseline.to_dict() == explicit_none.to_dict()

    def test_default_path_has_no_research_portfolio_metadata(self):
        run = run_commerce_mvp_slice(query="portable espresso maker", signal_fixture_path=FIXTURE)
        assert "research_portfolio" not in run.metadata


class TestResearchPortfolioOptIn:
    def test_selects_portfolio_top_candidate(self):
        # Without any supplier/competition evidence, confidence never
        # exceeds the honest ~0.24 floor (see docs/OPPORTUNITY_SCORING.md),
        # so every fixture candidate lands in high_uncertainty and
        # top_candidate_id is correctly None -- supply real evidence for
        # one candidate to exercise a genuine, confident top pick.
        rows = _load_signals(FIXTURE)
        candidates = build_opportunity_candidates_from_signals(rows, "commerce-mvp-dry-run", "portable espresso maker", 5)
        target_id = candidates[0].candidate_id
        portfolio, _ = _portfolio_for_fixture(with_strong_evidence_for=target_id)
        assert portfolio.top_candidate_id == target_id
        run = run_commerce_mvp_slice(query="portable espresso maker", signal_fixture_path=FIXTURE, research_portfolio=portfolio)
        assert run.selected_candidate.candidate_id == target_id

    def test_stores_portfolio_in_metadata(self):
        rows = _load_signals(FIXTURE)
        candidates = build_opportunity_candidates_from_signals(rows, "commerce-mvp-dry-run", "portable espresso maker", 5)
        portfolio, _ = _portfolio_for_fixture(with_strong_evidence_for=candidates[0].candidate_id)
        run = run_commerce_mvp_slice(query="portable espresso maker", signal_fixture_path=FIXTURE, research_portfolio=portfolio)
        assert "research_portfolio" in run.metadata
        assert run.metadata["research_portfolio"]["top_candidate_id"] == portfolio.top_candidate_id

    def test_takes_priority_over_use_opportunity_ranking(self):
        # Force the portfolio's top pick to a *different* candidate than
        # whichever rank_opportunities()/select_candidate() would choose,
        # and confirm the portfolio wins.
        rows = _load_signals(FIXTURE)
        all_candidates = build_opportunity_candidates_from_signals(rows, "commerce-mvp-dry-run", "portable espresso maker", 5)
        other_id = sorted(c.candidate_id for c in all_candidates)[-1]
        portfolio, _ = _portfolio_for_fixture(force_top_id=other_id)
        run = run_commerce_mvp_slice(
            query="portable espresso maker", signal_fixture_path=FIXTURE,
            use_opportunity_ranking=True, research_portfolio=portfolio,
        )
        assert run.selected_candidate.candidate_id == other_id

    def test_economics_grounded_by_supplier_evidence_supplied_alongside_portfolio(self):
        portfolio, _ = _portfolio_for_fixture()
        evidence = SupplierEvidenceResult(attempted=True, unit_cost=9.5, shipping_cost=2.0, source_url="https://cj.example/x")
        run = run_commerce_mvp_slice(
            query="portable espresso maker", signal_fixture_path=FIXTURE,
            research_portfolio=portfolio, supplier_evidence=evidence,
        )
        assert run.unit_economics_summary.source == "partial_observed_supplier_evidence"
        assert run.unit_economics_summary.assumed_unit_cost == 9.5

    def test_unmatched_top_candidate_id_falls_back_to_default_selection(self):
        portfolio, _ = _portfolio_for_fixture(force_top_id=None)
        import dataclasses
        bogus = dataclasses.replace(portfolio, top_candidate_id="commerce-candidate-does-not-exist")
        baseline = run_commerce_mvp_slice(query="portable espresso maker", signal_fixture_path=FIXTURE)
        run = run_commerce_mvp_slice(query="portable espresso maker", signal_fixture_path=FIXTURE, research_portfolio=bogus)
        assert run.selected_candidate.candidate_id == baseline.selected_candidate.candidate_id

    def test_deterministic_replay(self):
        portfolio, _ = _portfolio_for_fixture()
        first = run_commerce_mvp_slice(query="portable espresso maker", signal_fixture_path=FIXTURE, research_portfolio=portfolio)
        second = run_commerce_mvp_slice(query="portable espresso maker", signal_fixture_path=FIXTURE, research_portfolio=portfolio)
        assert first.to_dict() == second.to_dict()
