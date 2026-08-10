"""Tests for backend.mvp_commerce.product_research."""
from __future__ import annotations

from backend.adapters.research.competition_evidence import CompetitorOffer
from backend.contracts.events import Event
from backend.mvp_commerce import opportunity_scoring as scoring_mod
from backend.mvp_commerce import product_research as mod
from backend.mvp_commerce.competition_intelligence import MarketIntelligenceReport
from backend.mvp_commerce.models import OpportunityCandidate
from backend.mvp_commerce.supplier_evidence import SupplierEvidenceResult


def _candidate(candidate_id: str, product_name: str, *, source_count=3, local_score=80.0, recency=100.0,
               category_name: str = "public_signal_hypothesis") -> OpportunityCandidate:
    return OpportunityCandidate(
        candidate_id, "workspace-1", "portable espresso maker", product_name, category_name,
        ("sig-1",), ("title",), ("https://example.com/a",), source_count, local_score, recency,
        "moderate", "low", ("Supplier cost is unverified.",), ("Demand is unverified.",),
        ("No demand or ROAS claim is supported.",), "Collect supplier, price, and customer-problem evidence manually.",
    )


def _offer(price=32.0, brand="Acme", rating=4.2, review_count=80, source="public_storefront"):
    return CompetitorOffer(
        source=source, source_url="https://example.com/x", crawl_timestamp=1_700_000_000.0,
        external_listing_id="l1", title="Portable Espresso Maker", field_status={"price": "observed"},
        price=price, currency="USD", brand=brand, rating=rating, review_count=review_count,
    )


def _market_report(*, generated_at=1_700_000_000.0, confidence=0.8, offers=None, median_price=30.0):
    return MarketIntelligenceReport(
        query="portable espresso maker", generated_at=generated_at, offers=tuple(offers or (_offer(),)),
        observed_competitor_count=1, observed_median_price=median_price, observed_mean_price=median_price,
        observed_min_price=median_price, observed_max_price=median_price, observed_pricing_variance=1.0,
        observed_shipping_min=None, observed_shipping_max=None, observed_review_density=80.0,
        observed_rating_mean=4.2, observed_brand_diversity=1.0, observed_seller_diversity=1.0,
        observed_availability_ratio=1.0, market_maturity="emerging", market_saturation=0.1, confidence=confidence,
    )


def _supplier_evidence(unit_cost=9.5):
    return SupplierEvidenceResult(attempted=True, unit_cost=unit_cost, shipping_cost=2.0, source_url="https://cj.example/x")


def _scored_research_candidate(candidate_id, product_name, *, local_score=80.0, supplier_evidence=None, competition_evidence=None, margin=None):
    candidate = _candidate(candidate_id, product_name, local_score=local_score)
    score = scoring_mod.score_opportunity(candidate, supplier_evidence=supplier_evidence, competition_evidence=competition_evidence, margin=margin)
    return mod.ResearchCandidate(candidate_id, candidate, score, supplier_evidence, competition_evidence)


class TestNormalization:
    def test_normalize_title_strips_stopwords_and_punctuation(self):
        assert mod.normalize_title("The Portable Espresso Maker, for Travel!") == "portable espresso maker travel"

    def test_normalize_title_empty(self):
        assert mod.normalize_title("") == ""
        assert mod.normalize_title(None) == ""

    def test_normalize_brand_strips_suffixes(self):
        assert mod.normalize_brand("Acme Inc.") == "acme"
        assert mod.normalize_brand("Zenith, LLC") == "zenith"

    def test_normalize_category_lowercases_and_strips(self):
        assert mod.normalize_category("  Kitchen Appliances!! ") == "kitchen appliances"


class TestIdentityResolution:
    def test_resolve_identity_without_competition_evidence_has_no_brand(self):
        research_candidate = mod.ResearchCandidate("c1", _candidate("c1", "Portable Espresso Maker"))
        identity = mod.resolve_identity(research_candidate)
        assert identity.normalized_title == "portable espresso maker"
        assert identity.normalized_brand == ""
        assert identity.confidence < 1.0

    def test_resolve_identity_with_competition_evidence_has_brand(self):
        research_candidate = mod.ResearchCandidate("c1", _candidate("c1", "Portable Espresso Maker"), competition_evidence=_market_report())
        identity = mod.resolve_identity(research_candidate)
        assert identity.normalized_brand == "acme"

    def test_never_raises_on_empty_title(self):
        research_candidate = mod.ResearchCandidate("c1", _candidate("c1", ""))
        identity = mod.resolve_identity(research_candidate)
        assert identity.normalized_title == ""


class TestDuplicateGrouping:
    def test_near_identical_titles_group_as_duplicate(self):
        candidates = [
            mod.ResearchCandidate("c1", _candidate("c1", "Portable Espresso Maker")),
            mod.ResearchCandidate("c2", _candidate("c2", "Portable Espresso Maker Deluxe")),
        ]
        groups = mod.group_duplicates(candidates, duplicate_threshold=0.5, variant_threshold=0.3)
        assert len(groups) == 1
        assert groups[0].kind == "duplicate"
        assert set(groups[0].member_ids) == {"c1", "c2"}

    def test_dissimilar_titles_never_merge(self):
        candidates = [
            mod.ResearchCandidate("c1", _candidate("c1", "Portable Espresso Maker")),
            mod.ResearchCandidate("c2", _candidate("c2", "Standing Desk Converter")),
        ]
        groups = mod.group_duplicates(candidates)
        assert len(groups) == 2
        assert all(group.kind == "unique" for group in groups)

    def test_uncertain_similarity_never_silently_merged(self):
        # Below variant_threshold must never merge, regardless of brand.
        candidates = [
            mod.ResearchCandidate("c1", _candidate("c1", "Portable Espresso Maker")),
            mod.ResearchCandidate("c2", _candidate("c2", "Wireless Bluetooth Headphones")),
        ]
        groups = mod.group_duplicates(candidates, variant_threshold=0.9)
        assert len(groups) == 2

    def test_empty_candidates_returns_empty(self):
        assert mod.group_duplicates([]) == []

    def test_single_candidate_is_unique(self):
        groups = mod.group_duplicates([mod.ResearchCandidate("c1", _candidate("c1", "Widget"))])
        assert len(groups) == 1
        assert groups[0].kind == "unique"
        assert groups[0].member_ids == ("c1",)


class TestClustering:
    def test_similar_titles_cluster_together(self):
        candidates = [
            mod.ResearchCandidate("c1", _candidate("c1", "Portable Espresso Maker")),
            mod.ResearchCandidate("c2", _candidate("c2", "Portable Espresso Machine")),
            mod.ResearchCandidate("c3", _candidate("c3", "Standing Desk Converter")),
        ]
        clusters = mod.build_clusters(candidates, threshold=0.5)
        cluster_by_member = {member: cluster.cluster_id for cluster in clusters for member in cluster.member_ids}
        assert cluster_by_member["c1"] == cluster_by_member["c2"]
        assert cluster_by_member["c3"] != cluster_by_member["c1"]

    def test_cluster_reports_price_range_and_diversity(self):
        candidates = [
            mod.ResearchCandidate("c1", _candidate("c1", "Portable Espresso Maker"), supplier_evidence=_supplier_evidence(9.5), competition_evidence=_market_report(median_price=30.0)),
            mod.ResearchCandidate("c2", _candidate("c2", "Portable Espresso Machine"), supplier_evidence=_supplier_evidence(12.0), competition_evidence=_market_report(median_price=28.0)),
        ]
        clusters = mod.build_clusters(candidates, threshold=0.5)
        assert len(clusters) == 1
        cluster = clusters[0]
        assert cluster.price_range["min"] is not None
        assert cluster.price_range["max"] is not None
        assert cluster.supplier_diversity == 1  # both use the same default "cj_public_page" supplier label
        assert cluster.competition_diversity >= 1

    def test_category_name_constant_never_used_for_naming(self):
        # OpportunityCandidate.category_name is always "public_signal_hypothesis"
        # in this pipeline -- cluster names must come from titles, not that tag.
        candidates = [mod.ResearchCandidate("c1", _candidate("c1", "Portable Espresso Maker"))]
        clusters = mod.build_clusters(candidates)
        assert "public_signal_hypothesis" not in clusters[0].name
        assert "portable espresso maker" in clusters[0].name

    def test_empty_candidates_returns_empty_clusters(self):
        assert mod.build_clusters([]) == []


class TestResearchQuality:
    def test_zero_candidates_all_zero(self):
        quality = mod.compute_research_quality([])
        assert quality.evidence_coverage == 0.0
        assert quality.research_completeness == 0.0

    def test_full_evidence_raises_coverage(self):
        candidates = [mod.ResearchCandidate("c1", _candidate("c1", "Widget"), supplier_evidence=_supplier_evidence(), competition_evidence=_market_report())]
        quality = mod.compute_research_quality(candidates, now=1_700_000_100.0)
        assert quality.supplier_coverage == 1.0
        assert quality.competition_coverage == 1.0
        assert quality.observed_pricing_coverage == 1.0
        assert quality.research_freshness == 1.0

    def test_stale_evidence_reduces_freshness(self):
        candidates = [mod.ResearchCandidate("c1", _candidate("c1", "Widget"), competition_evidence=_market_report(generated_at=1_700_000_000.0))]
        quality = mod.compute_research_quality(candidates, now=1_700_100_000.0, freshness_window_s=3600.0)
        assert quality.research_freshness == 0.0

    def test_unknown_ratio_reflects_opportunity_score(self):
        candidate = _scored_research_candidate("c1", "Widget")
        quality = mod.compute_research_quality([candidate])
        assert 0.0 < quality.unknown_ratio <= 1.0

    def test_no_scores_defaults_unknown_ratio_to_full_unknown(self):
        candidates = [mod.ResearchCandidate("c1", _candidate("c1", "Widget"))]
        quality = mod.compute_research_quality(candidates)
        assert quality.unknown_ratio == 1.0


class TestResearchPortfolio:
    def test_strong_evidence_candidate_avoids_uncertainty_and_rejection(self):
        strong = _scored_research_candidate(
            "c1", "Portable Espresso Maker", local_score=95.0,
            supplier_evidence=_supplier_evidence(9.5), competition_evidence=_market_report(confidence=0.9), margin=None,
        )
        # composite_score=81.26, confidence=0.5368 -- above the top-bucket
        # composite threshold but below its confidence threshold (0.6), and
        # this candidate has real dimension risks (weight/variant/shipping
        # data unavailable), so it lands in high_risk, not top -- a
        # genuinely different, still-informative bucket, never uncertain
        # or rejected outright.
        portfolio = mod.build_research_portfolio([strong], workspace_id="ws", query="x", generated_at=1.0)
        assert strong.candidate_id in {e.candidate_id for e in portfolio.high_risk_opportunities}
        assert strong.candidate_id not in {e.candidate_id for e in portfolio.high_uncertainty_opportunities}
        assert strong.candidate_id not in {e.candidate_id for e in portfolio.rejected_candidates}

    def test_unscored_candidate_lands_in_high_uncertainty(self):
        candidates = [mod.ResearchCandidate("c1", _candidate("c1", "Widget"))]
        portfolio = mod.build_research_portfolio(candidates, workspace_id="ws", query="x", generated_at=1.0)
        assert "c1" in {e.candidate_id for e in portfolio.high_uncertainty_opportunities}

    def test_every_candidate_lands_in_exactly_one_bucket(self):
        candidates = [
            _scored_research_candidate("c1", "Portable Espresso Maker", local_score=95.0, supplier_evidence=_supplier_evidence(), competition_evidence=_market_report(confidence=0.9)),
            mod.ResearchCandidate("c2", _candidate("c2", "Widget")),
            _scored_research_candidate("c3", "Standing Desk", local_score=10.0),
        ]
        portfolio = mod.build_research_portfolio(candidates, workspace_id="ws", query="x", generated_at=1.0)
        all_buckets = (portfolio.top_opportunities + portfolio.emerging_opportunities + portfolio.undervalued_opportunities +
                       portfolio.high_risk_opportunities + portfolio.high_uncertainty_opportunities + portfolio.rejected_candidates)
        bucket_ids = [entry.candidate_id for entry in all_buckets]
        assert sorted(bucket_ids) == ["c1", "c2", "c3"]
        assert len(bucket_ids) == len(set(bucket_ids))

    def test_empty_candidates_yields_empty_portfolio(self):
        portfolio = mod.build_research_portfolio([], workspace_id="ws", query="x", generated_at=1.0)
        assert portfolio.top_candidate_id is None
        assert portfolio.candidate_ids == ()

    def test_deterministic_given_identical_inputs(self):
        candidates = [_scored_research_candidate("c1", "Portable Espresso Maker", local_score=70.0)]
        first = mod.build_research_portfolio(candidates, workspace_id="ws", query="x", generated_at=1.0)
        second = mod.build_research_portfolio(candidates, workspace_id="ws", query="x", generated_at=1.0)
        assert first.to_dict() == second.to_dict()

    def test_low_score_no_evidence_candidate_is_high_uncertainty(self):
        # confidence=0.2368 (below the 0.3 floor with zero gathered
        # evidence) takes priority over the low composite score itself.
        candidate = _candidate("c1", "Widget", local_score=1.0, recency=0.0)
        score = scoring_mod.score_opportunity(candidate)
        research_candidate = mod.ResearchCandidate("c1", candidate, score)
        portfolio = mod.build_research_portfolio([research_candidate], workspace_id="ws", query="x", generated_at=1.0)
        assert "c1" in {e.candidate_id for e in portfolio.high_uncertainty_opportunities}


class TestPortfolioComparison:
    def test_new_candidate_detected(self):
        empty = mod.build_research_portfolio([], workspace_id="ws", query="x", generated_at=1.0)
        candidates = [_scored_research_candidate("c1", "Widget", local_score=90.0, supplier_evidence=_supplier_evidence(), competition_evidence=_market_report(confidence=0.9))]
        current = mod.build_research_portfolio(candidates, workspace_id="ws", query="x", generated_at=2.0)
        comparison = mod.compare_portfolios(empty, current)
        assert any(m.candidate_id == "c1" and m.change_kind == "new" for m in comparison.movements)

    def test_removed_candidate_detected(self):
        candidates = [mod.ResearchCandidate("c1", _candidate("c1", "Widget"))]
        previous = mod.build_research_portfolio(candidates, workspace_id="ws", query="x", generated_at=1.0)
        current = mod.build_research_portfolio([], workspace_id="ws", query="x", generated_at=2.0)
        comparison = mod.compare_portfolios(previous, current)
        assert any(m.candidate_id == "c1" and m.change_kind == "removed" for m in comparison.movements)

    def test_score_improvement_detected(self):
        low = [_scored_research_candidate("c1", "Widget", local_score=20.0)]
        high = [_scored_research_candidate("c1", "Widget", local_score=95.0, supplier_evidence=_supplier_evidence(), competition_evidence=_market_report(confidence=0.9))]
        previous = mod.build_research_portfolio(low, workspace_id="ws", query="x", generated_at=1.0)
        current = mod.build_research_portfolio(high, workspace_id="ws", query="x", generated_at=2.0)
        comparison = mod.compare_portfolios(previous, current)
        movement = next(m for m in comparison.movements if m.candidate_id == "c1")
        assert movement.score_delta is not None and movement.score_delta > 0
        assert movement.change_kind == "improved"

    def test_unchanged_candidate_reports_unchanged(self):
        candidates = [_scored_research_candidate("c1", "Widget", local_score=70.0)]
        portfolio = mod.build_research_portfolio(candidates, workspace_id="ws", query="x", generated_at=1.0)
        comparison = mod.compare_portfolios(portfolio, portfolio)
        assert all(m.change_kind == "unchanged" for m in comparison.movements)


class TestProductResearchEvents:
    def test_emits_expected_event_types(self):
        candidates = [_scored_research_candidate("c1", "Portable Espresso Maker", local_score=95.0, supplier_evidence=_supplier_evidence(), competition_evidence=_market_report(confidence=0.9))]
        portfolio = mod.build_research_portfolio(candidates, workspace_id="ws", query="x", generated_at=1.0)
        events = mod.product_research_events(portfolio, candidates, run_id="run-1")
        types = [e.event_type for e in events]
        assert types[0] == "candidate_discovered"
        assert "research_portfolio_updated" in types
        assert types[-1] == "research_completed"
        assert all(isinstance(e, Event) for e in events)

    def test_ranking_changed_events_only_for_real_movement(self):
        candidates = [_scored_research_candidate("c1", "Widget", local_score=70.0)]
        portfolio = mod.build_research_portfolio(candidates, workspace_id="ws", query="x", generated_at=1.0)
        comparison = mod.compare_portfolios(portfolio, portfolio)
        events = mod.product_research_events(portfolio, candidates, run_id="run-1", comparison=comparison)
        assert "ranking_changed" not in [e.event_type for e in events]

    def test_events_carry_advisory_metadata(self):
        candidates = [_scored_research_candidate("c1", "Widget", local_score=70.0)]
        portfolio = mod.build_research_portfolio(candidates, workspace_id="ws", query="x", generated_at=1.0)
        for event in mod.product_research_events(portfolio, candidates, run_id="run-1"):
            assert event.metadata["dry_run"] is True
            assert event.metadata["advisory"] is True
            assert event.metadata["no_order_authority"] is True

    def test_deterministic_event_ids(self):
        candidates = [_scored_research_candidate("c1", "Widget", local_score=70.0)]
        portfolio = mod.build_research_portfolio(candidates, workspace_id="ws", query="x", generated_at=1.0)
        first = mod.product_research_events(portfolio, candidates, run_id="run-1")
        second = mod.product_research_events(portfolio, candidates, run_id="run-1")
        assert [e.event_id for e in first] == [e.event_id for e in second]


class TestBuildResearchCandidates:
    def test_aggregates_all_evidence_sources(self):
        candidate = _candidate("c1", "Widget")
        score = scoring_mod.score_opportunity(candidate)
        supplier = _supplier_evidence()
        competition = _market_report()
        research_candidates = mod.build_research_candidates(
            [candidate], scores_by_id={"c1": score}, supplier_evidence_by_id={"c1": supplier},
            competition_evidence_by_id={"c1": competition}, additional_evidence_by_id={"c1": {"shopify": {"present": True}}},
        )
        assert len(research_candidates) == 1
        result = research_candidates[0]
        assert result.opportunity_score is score
        assert result.supplier_evidence is supplier
        assert result.competition_evidence is competition
        assert result.additional_evidence == {"shopify": {"present": True}}

    def test_missing_evidence_maps_default_to_none(self):
        candidate = _candidate("c1", "Widget")
        research_candidates = mod.build_research_candidates([candidate])
        result = research_candidates[0]
        assert result.opportunity_score is None
        assert result.supplier_evidence is None
        assert result.competition_evidence is None
        assert result.additional_evidence == {}
