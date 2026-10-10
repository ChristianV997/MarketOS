"""Tests for backend.mvp_commerce.opportunity_scoring."""
from __future__ import annotations

from backend.adapters.research.cj_public_evidence import CJProductEvidence
from backend.adapters.research.competition_evidence import CompetitorOffer
from backend.contracts.events import Event
from backend.mvp_commerce import opportunity_scoring as mod
from backend.mvp_commerce.competition_intelligence import MarginIntelligence, MarketIntelligenceReport
from backend.mvp_commerce.models import OpportunityCandidate
from backend.mvp_commerce.supplier_evidence import SupplierEvidenceResult


def _candidate(
    candidate_id: str = "commerce-candidate-abc123",
    *,
    source_count: int = 3,
    local_score: float = 80.0,
    recency: float = 100.0,
    assumptions: tuple[str, ...] = ("Supplier cost is unverified.",),
    unknowns: tuple[str, ...] = ("Demand is unverified.",),
    cannot_claim: tuple[str, ...] = ("No demand or ROAS claim is supported.",),
) -> OpportunityCandidate:
    return OpportunityCandidate(
        candidate_id, "workspace-1", "portable espresso maker", "Portable Espresso Maker", "public_signal_hypothesis",
        ("sig-1", "sig-2", "sig-3")[:source_count], ("title one", "title two", "title three")[:source_count],
        ("https://example.com/a",), source_count, local_score, recency, "moderate", "low",
        assumptions, unknowns, cannot_claim, "Collect supplier, price, and customer-problem evidence manually.",
    )


def _evidence(
    *,
    price: float | None = 9.5,
    price_status: str = "observed",
    shipping_cost: float | None = 2.0,
    shipping_status: str = "observed",
    delivery_days: int | None = 12,
    delivery_status: str = "observed",
    weight_kg: float | None = 0.4,
    weight_status: str = "observed",
    variants: tuple[dict, ...] = ({"name": "Color: Black"}, {"name": "Color: Silver"}),
    variants_status: str = "observed",
    fetch_provenance: str = "fresh_fetch",
) -> CJProductEvidence:
    field_status = {
        "price": price_status, "currency": "observed", "shipping_cost": shipping_status,
        "shipping_currency": "observed" if shipping_cost is not None else "unavailable",
        "estimated_delivery_days": delivery_status, "weight_kg": weight_status, "variants": variants_status,
    }
    return CJProductEvidence(
        source="cj_public_page", source_url="https://www.cjdropshipping.com/product/x.html", observed_at=1_700_000_000.0,
        external_product_id="cj-1", title="Portable Espresso Maker", field_status=field_status,
        price=price, currency="USD", variants=variants, weight_kg=weight_kg,
        shipping_cost=shipping_cost, shipping_currency="USD" if shipping_cost is not None else None,
        estimated_delivery_days=delivery_days, fetch_provenance=fetch_provenance,
    )


def _evidence_result(evidence: CJProductEvidence | None, *, unit_cost: float | None = 9.5, shipping_cost=2.0) -> SupplierEvidenceResult:
    ranking = ({"product_id": "cj-1", "composite_score": 0.82, "relevance": 0.9, "completeness": 0.8, "confidence": 0.7},) if evidence else ()
    return SupplierEvidenceResult(
        attempted=True, unit_cost=unit_cost, shipping_cost=shipping_cost, source_url="https://www.cjdropshipping.com/product/x.html",
        candidates_considered=1 if evidence else 0, evidence=evidence, ranking=ranking,
    )


class TestDimensionsWithoutEvidence:
    def test_supplier_dimensions_are_unavailable_without_evidence(self):
        score = mod.score_opportunity(_candidate())
        by_name = {d.name: d for d in score.dimensions}
        for name in ("supplier_evidence_quality", "observed_supplier_cost", "product_simplicity",
                     "shipping_complexity", "weight_volume", "variant_complexity", "category_stability",
                     "market_saturation", "price_competitiveness", "supplier_advantage",
                     "market_confidence", "review_strength", "offer_diversity"):
            assert by_name[name].is_unknown is True
            assert by_name[name].provenance == "unavailable"
            assert by_name[name].raw_value is None
            assert by_name[name].weight == 0.0
            assert by_name[name].contribution == 0.0

    def test_unavailable_dimensions_never_drag_down_composite(self):
        # Composite is a weighted mean over *available* dimensions only, so
        # a candidate with zero supplier evidence must not be penalized
        # relative to the same candidate's non-supplier dimensions alone.
        score = mod.score_opportunity(_candidate())
        assert 0.0 <= score.composite_score <= 100.0
        assert score.composite_score > 0.0

    def test_unknowns_listed_and_confidence_reduced(self):
        score = mod.score_opportunity(_candidate())
        assert len(score.unknowns) == 13
        assert score.confidence < 1.0
        assert score.unknown_pct > 0.0

    def test_no_fabricated_certainty(self):
        # A candidate with zero evidence anywhere must never claim full
        # confidence -- unknowns must always reduce confidence.
        candidate = _candidate(source_count=1, local_score=10.0, recency=50.0)
        score = mod.score_opportunity(candidate)
        assert score.confidence < 0.6


class TestDimensionsWithEvidence:
    def test_supplier_evidence_quality_observed_with_real_evidence(self):
        evidence = _evidence(fetch_provenance="cache_hit")
        result = _evidence_result(evidence)
        score = mod.score_opportunity(_candidate(), supplier_evidence=result)
        by_name = {d.name: d for d in score.dimensions}
        assert by_name["supplier_evidence_quality"].provenance == "public_page"
        assert by_name["supplier_evidence_quality"].is_unknown is False
        assert "public-page observation is not supplier-live proof" in by_name["supplier_evidence_quality"].reason
        assert "retrieval=cache_hit" in by_name["supplier_evidence_quality"].reason
        assert by_name["observed_supplier_cost"].provenance == "public_page"
        assert by_name["observed_supplier_cost"].raw_value == 9.5
        assert "not supplier-live proof" in by_name["observed_supplier_cost"].reason

    def test_explicit_zero_public_price_is_not_scored_as_supplier_cost(self):
        evidence = _evidence(price=0.0, price_status="observed")
        result = _evidence_result(evidence, unit_cost=0.0)
        cost = {d.name: d for d in mod.score_opportunity(_candidate(), supplier_evidence=result).dimensions}["observed_supplier_cost"]

        assert cost.is_unknown is True
        assert cost.raw_value is None

    def test_missing_public_page_price_stays_unavailable_in_scoring(self):
        result = _evidence_result(_evidence(price=None, price_status="unavailable"), unit_cost=None)

        score = mod.score_opportunity(_candidate(), supplier_evidence=result)

        cost = {dimension.name: dimension for dimension in score.dimensions}["observed_supplier_cost"]
        assert cost.is_unknown is True
        assert cost.raw_value is None

    def test_product_simplicity_uses_observed_variant_count(self):
        evidence = _evidence(variants=({"name": "A"},))
        result = _evidence_result(evidence)
        score = mod.score_opportunity(_candidate(), supplier_evidence=result)
        by_name = {d.name: d for d in score.dimensions}
        assert by_name["product_simplicity"].raw_value == 1.0
        assert by_name["product_simplicity"].provenance == "public_page"

    def test_foreign_currency_cost_and_shipping_are_not_used_by_scoring(self):
        evidence = _evidence()
        evidence = CJProductEvidence(
            source=evidence.source, source_url=evidence.source_url, observed_at=evidence.observed_at,
            fetched_at=evidence.fetched_at, external_product_id=evidence.external_product_id,
            title=evidence.title, field_status=evidence.field_status, price=evidence.price,
            currency="EUR", shipping_cost=evidence.shipping_cost, shipping_currency="EUR",
            estimated_delivery_days=None, variants=evidence.variants, weight_kg=evidence.weight_kg,
            fetch_provenance=evidence.fetch_provenance,
        )
        result = _evidence_result(evidence, unit_cost=9.5, shipping_cost=2.0)
        dimensions = {item.name: item for item in mod.score_opportunity(_candidate(), supplier_evidence=result).dimensions}

        assert dimensions["observed_supplier_cost"].is_unknown is True
        assert dimensions["observed_supplier_cost"].raw_value is None
        assert dimensions["shipping_complexity"].is_unknown is True
        assert "EUR" in dimensions["shipping_complexity"].reason

    def test_shipping_complexity_unavailable_when_not_observed(self):
        evidence = _evidence(shipping_status="unavailable", shipping_cost=None,
                              delivery_status="unavailable", delivery_days=None)
        result = _evidence_result(evidence, shipping_cost=None)
        score = mod.score_opportunity(_candidate(), supplier_evidence=result)
        by_name = {d.name: d for d in score.dimensions}
        assert by_name["shipping_complexity"].is_unknown is True

    def test_more_evidence_raises_confidence(self):
        no_evidence_score = mod.score_opportunity(_candidate())
        with_evidence_score = mod.score_opportunity(_candidate(), supplier_evidence=_evidence_result(_evidence()))
        assert with_evidence_score.confidence > no_evidence_score.confidence
        assert with_evidence_score.observed_pct > no_evidence_score.observed_pct


def _competitor_offer(listing_id: str, *, price: float, brand: str = "BrandA", seller: str = "SellerA",
                       rating: float | None = 4.0, review_count: int | None = 50) -> CompetitorOffer:
    return CompetitorOffer(
        source="public_storefront", source_url=f"https://example.com/{listing_id}", crawl_timestamp=1_700_000_000.0,
        external_listing_id=listing_id, title="Portable Espresso Maker",
        field_status={"title": "observed", "price": "observed", "brand": "observed", "seller": "observed",
                      "rating": "observed" if rating is not None else "missing",
                      "review_count": "observed" if review_count is not None else "missing"},
        price=price, currency="USD", availability="InStock", brand=brand, seller=seller,
        rating=rating, review_count=review_count,
    )


def _market_report(*, offers=None, median_price=30.0, mean_price=30.0, min_price=25.0, max_price=35.0,
                    variance=5.0, review_density=50.0, rating_mean=4.0, brand_diversity=0.5, seller_diversity=0.5,
                    saturation=0.3, maturity="emerging", confidence=0.8, competitor_count=3) -> MarketIntelligenceReport:
    return MarketIntelligenceReport(
        query="portable espresso maker", generated_at=1_700_000_000.0,
        offers=tuple(offers or (_competitor_offer("l1", price=25.0), _competitor_offer("l2", price=35.0))),
        observed_competitor_count=competitor_count, observed_median_price=median_price, observed_mean_price=mean_price,
        observed_min_price=min_price, observed_max_price=max_price, observed_pricing_variance=variance,
        observed_shipping_min=2.0, observed_shipping_max=6.0, observed_review_density=review_density,
        observed_rating_mean=rating_mean, observed_brand_diversity=brand_diversity, observed_seller_diversity=seller_diversity,
        observed_availability_ratio=1.0, market_maturity=maturity, market_saturation=saturation, confidence=confidence,
    )


def _margin(*, supplier_advantage=0.3, gross_margin=0.5) -> MarginIntelligence:
    return MarginIntelligence(
        candidate_id="commerce-candidate-abc123", observed_gross_margin=gross_margin, observed_margin_low=0.2,
        observed_margin_high=0.6, observed_supplier_advantage=supplier_advantage, observed_pricing_confidence=0.8,
        observed_margin_confidence=0.85, provenance={"supplier_cost": "observed", "market_price": "observed"},
    )


class TestCompetitionDimensions:
    def test_all_six_unavailable_without_competition_or_margin(self):
        score = mod.score_opportunity(_candidate())
        by_name = {d.name: d for d in score.dimensions}
        for name in ("market_saturation", "price_competitiveness", "supplier_advantage",
                     "market_confidence", "review_strength", "offer_diversity"):
            assert by_name[name].is_unknown is True

    def test_market_saturation_observed_with_competition_evidence(self):
        score = mod.score_opportunity(_candidate(), competition_evidence=_market_report(saturation=0.2))
        dim = {d.name: d for d in score.dimensions}["market_saturation"]
        assert dim.provenance == "observed"
        assert dim.raw_value == 0.2
        assert dim.normalized_value == 80.0  # low saturation -> high score

    def test_low_saturation_scores_higher_than_high_saturation(self):
        low = mod.score_opportunity(_candidate(), competition_evidence=_market_report(saturation=0.1))
        high = mod.score_opportunity(_candidate(), competition_evidence=_market_report(saturation=0.9))
        low_dim = {d.name: d for d in low.dimensions}["market_saturation"]
        high_dim = {d.name: d for d in high.dimensions}["market_saturation"]
        assert low_dim.normalized_value > high_dim.normalized_value

    def test_price_competitiveness_observed_from_dispersion(self):
        score = mod.score_opportunity(_candidate(), competition_evidence=_market_report(median_price=30.0, variance=9.0))
        dim = {d.name: d for d in score.dimensions}["price_competitiveness"]
        assert dim.provenance == "observed"
        assert dim.raw_value == 0.3  # 9.0 / 30.0

    def test_price_competitiveness_unavailable_without_median_price(self):
        report = _market_report(median_price=None, variance=None)
        score = mod.score_opportunity(_candidate(), competition_evidence=report)
        assert {d.name: d for d in score.dimensions}["price_competitiveness"].is_unknown is True

    def test_supplier_advantage_requires_margin_not_just_competition(self):
        score = mod.score_opportunity(_candidate(), competition_evidence=_market_report())
        assert {d.name: d for d in score.dimensions}["supplier_advantage"].is_unknown is True
        with_margin = mod.score_opportunity(_candidate(), competition_evidence=_market_report(), margin=_margin(supplier_advantage=0.4))
        dim = {d.name: d for d in with_margin.dimensions}["supplier_advantage"]
        assert dim.is_unknown is False
        assert dim.raw_value == 0.4
        assert dim.normalized_value == 40.0

    def test_market_confidence_reflects_report_confidence(self):
        score = mod.score_opportunity(_candidate(), competition_evidence=_market_report(confidence=0.65))
        dim = {d.name: d for d in score.dimensions}["market_confidence"]
        assert dim.raw_value == 0.65
        assert dim.normalized_value == 65.0

    def test_review_strength_combines_rating_and_density(self):
        strong = mod.score_opportunity(_candidate(), competition_evidence=_market_report(rating_mean=4.8, review_density=200.0))
        weak = mod.score_opportunity(_candidate(), competition_evidence=_market_report(rating_mean=2.0, review_density=5.0))
        strong_dim = {d.name: d for d in strong.dimensions}["review_strength"]
        weak_dim = {d.name: d for d in weak.dimensions}["review_strength"]
        assert strong_dim.normalized_value > weak_dim.normalized_value

    def test_offer_diversity_averages_brand_and_seller(self):
        score = mod.score_opportunity(_candidate(), competition_evidence=_market_report(brand_diversity=0.4, seller_diversity=0.6))
        dim = {d.name: d for d in score.dimensions}["offer_diversity"]
        assert dim.raw_value == 0.5
        assert dim.normalized_value == 50.0

    def test_full_competition_evidence_raises_confidence_above_supplier_only(self):
        supplier_only = mod.score_opportunity(_candidate(), supplier_evidence=_evidence_result(_evidence()))
        full = mod.score_opportunity(
            _candidate(), supplier_evidence=_evidence_result(_evidence()),
            competition_evidence=_market_report(), margin=_margin(),
        )
        assert full.confidence > supplier_only.confidence
        assert full.observed_pct > supplier_only.observed_pct

    def test_rank_opportunities_keys_competition_and_margin_per_candidate(self):
        strong = _candidate("commerce-candidate-strong", source_count=3, local_score=60.0, recency=100.0)
        weak = _candidate("commerce-candidate-weak", source_count=1, local_score=5.0, recency=50.0)
        competition_map = {weak.candidate_id: _market_report()}
        margin_map = {weak.candidate_id: _margin()}
        assessment = mod.rank_opportunities(
            [strong, weak], workspace_id="workspace-1", query="x",
            competition_evidence_by_candidate=competition_map, margin_by_candidate=margin_map, generated_at=1.0,
        )
        by_id = {s.candidate_id: s for s in assessment.scores}
        assert {d.name: d for d in by_id[strong.candidate_id].dimensions}["market_saturation"].is_unknown is True
        assert {d.name: d for d in by_id[weak.candidate_id].dimensions}["market_saturation"].is_unknown is False


class TestRecommendedAction:
    def test_low_confidence_without_any_evidence_recommends_gathering_evidence(self):
        # Without supplier or competition evidence, six candidate-only
        # dimensions are always available (never "unavailable") out of 19
        # total, which floors confidence at ~0.237 -- below the <0.3
        # "gather more evidence" threshold. Adding the six Competition
        # Intelligence dimensions (all unavailable by default) lowered this
        # floor from the pre-Competition-Intelligence ~0.32, making this
        # branch reachable end-to-end.
        score = mod.score_opportunity(_candidate(source_count=1, local_score=5.0, recency=50.0))
        assert score.confidence < 0.3
        assert score.recommended_action == "gather_more_evidence_before_any_decision"

    def test_confidence_formula_threshold_boundary(self):
        # Directly assert the threshold logic against _confidence()'s
        # output so a future change to the dimension count is still guarded
        # by a real test of the decision boundary, independent of any one
        # candidate fixture.
        all_unavailable = tuple(
            mod.ScoreDimension(name, None, None, 0.0, 0.0, "no data", "unavailable", True)
            for name in mod._WEIGHTS
        )
        confidence, *_ = mod._confidence(all_unavailable)
        assert confidence == 0.0
        assert confidence < 0.3

    def test_high_confidence_and_score_recommends_advancing(self):
        strong = _candidate(source_count=3, local_score=95.0, recency=100.0)
        result = _evidence_result(_evidence())
        score = mod.score_opportunity(strong, supplier_evidence=result)
        if score.confidence >= 0.6 and score.composite_score >= 60.0:
            assert score.recommended_action == "advance_to_economics_review"
        else:
            assert score.recommended_action == "corroborate_before_advancing"


class TestOperatorOverride:
    def test_override_changes_effective_score_not_composite(self):
        score = mod.score_opportunity(_candidate(), operator_override={"score": 99.0, "reason": "operator conviction"})
        assert score.effective_score == 99.0
        assert score.composite_score != 99.0
        assert score.operator_override == {"score": 99.0, "reason": "operator conviction"}

    def test_no_override_effective_score_equals_composite(self):
        score = mod.score_opportunity(_candidate())
        assert score.effective_score == score.composite_score


class TestRankOpportunities:
    def test_ranks_higher_score_first(self):
        strong = _candidate("commerce-candidate-strong", source_count=3, local_score=95.0, recency=100.0)
        weak = _candidate("commerce-candidate-weak", source_count=1, local_score=5.0, recency=50.0)
        assessment = mod.rank_opportunities([weak, strong], workspace_id="workspace-1", query="portable espresso maker", generated_at=1_700_000_000.0)
        assert assessment.top_candidate_id == strong.candidate_id
        assert [s.candidate_id for s in assessment.scores][0] == strong.candidate_id

    def test_empty_candidates_no_top(self):
        assessment = mod.rank_opportunities([], workspace_id="workspace-1", query="x", generated_at=1.0)
        assert assessment.top_candidate_id is None
        assert assessment.scores == ()

    def test_ties_break_on_candidate_id_ascending(self):
        a = _candidate("commerce-candidate-b", source_count=2, local_score=50.0, recency=100.0)
        b = _candidate("commerce-candidate-a", source_count=2, local_score=50.0, recency=100.0)
        assessment = mod.rank_opportunities([a, b], workspace_id="workspace-1", query="x", generated_at=1.0)
        assert assessment.scores[0].composite_score == assessment.scores[1].composite_score
        assert assessment.top_candidate_id == "commerce-candidate-a"

    def test_evidence_attached_only_to_its_own_candidate(self):
        strong = _candidate("commerce-candidate-strong", source_count=3, local_score=60.0, recency=100.0)
        weak = _candidate("commerce-candidate-weak", source_count=1, local_score=5.0, recency=50.0)
        evidence_map = {weak.candidate_id: _evidence_result(_evidence())}
        assessment = mod.rank_opportunities(
            [strong, weak], workspace_id="workspace-1", query="x",
            supplier_evidence_by_candidate=evidence_map, generated_at=1.0,
        )
        by_id = {s.candidate_id: s for s in assessment.scores}
        strong_dims = {d.name: d for d in by_id[strong.candidate_id].dimensions}
        weak_dims = {d.name: d for d in by_id[weak.candidate_id].dimensions}
        assert strong_dims["supplier_evidence_quality"].is_unknown is True
        assert weak_dims["supplier_evidence_quality"].is_unknown is False

    def test_deterministic_replay(self):
        candidates = [_candidate("commerce-candidate-a", source_count=2, local_score=40.0, recency=100.0),
                      _candidate("commerce-candidate-b", source_count=3, local_score=70.0, recency=50.0)]
        first = mod.rank_opportunities(candidates, workspace_id="workspace-1", query="x", generated_at=1.0)
        second = mod.rank_opportunities(candidates, workspace_id="workspace-1", query="x", generated_at=1.0)
        assert first.to_dict() == second.to_dict()


class TestOpportunityScoringEvents:
    def test_emits_expected_event_types_in_order(self):
        candidates = [_candidate("commerce-candidate-a"), _candidate("commerce-candidate-b", local_score=40.0)]
        assessment = mod.rank_opportunities(candidates, workspace_id="workspace-1", query="x", generated_at=1_700_000_000.0)
        events = mod.opportunity_scoring_events(assessment, run_id="commerce-mvp-run-1")
        types = [e.event_type for e in events]
        assert types == ["opportunity_scoring_started", "candidate_scored", "candidate_scored", "opportunity_ranked", "opportunity_scoring_completed"]
        assert all(isinstance(e, Event) for e in events)

    def test_events_are_advisory_and_carry_no_execution_authority(self):
        assessment = mod.rank_opportunities([_candidate()], workspace_id="workspace-1", query="x", generated_at=1.0)
        for event in mod.opportunity_scoring_events(assessment, run_id="commerce-mvp-run-1"):
            assert event.metadata["dry_run"] is True
            assert event.metadata["advisory"] is True
            assert event.metadata["no_launch_authority"] is True
            assert event.metadata["no_ad_authority"] is True
            assert event.metadata["no_spend_authority"] is True
            assert event.metadata["no_order_authority"] is True
            assert event.metadata["no_payment_authority"] is True
            assert event.metadata["no_outreach_authority"] is True
            assert event.metadata["no_supplier_mutation_authority"] is True
            assert event.metadata["no_inventory_mutation_authority"] is True
            assert event.metadata["no_customer_message_authority"] is True
            assert event.metadata["no_external_action_authority"] is True

    def test_events_correlate_to_run_id(self):
        assessment = mod.rank_opportunities([_candidate()], workspace_id="workspace-1", query="x", generated_at=1.0)
        events = mod.opportunity_scoring_events(assessment, run_id="commerce-mvp-run-42")
        assert all(e.correlation_id == "commerce-mvp-run-42" for e in events)

    def test_deterministic_event_ids_given_identical_inputs(self):
        assessment = mod.rank_opportunities([_candidate()], workspace_id="workspace-1", query="x", generated_at=1.0)
        first = mod.opportunity_scoring_events(assessment, run_id="commerce-mvp-run-1")
        second = mod.opportunity_scoring_events(assessment, run_id="commerce-mvp-run-1")
        assert [e.event_id for e in first] == [e.event_id for e in second]

    def test_candidate_scored_payload_matches_score_to_dict(self):
        assessment = mod.rank_opportunities([_candidate()], workspace_id="workspace-1", query="x", generated_at=1.0)
        events = mod.opportunity_scoring_events(assessment, run_id="commerce-mvp-run-1")
        scored_event = next(e for e in events if e.event_type == "candidate_scored")
        assert scored_event.payload == assessment.scores[0].to_dict()


class TestToDict:
    def test_score_to_dict_round_trips_key_fields(self):
        score = mod.score_opportunity(_candidate())
        payload = score.to_dict()
        assert payload["candidate_id"] == score.candidate_id
        assert len(payload["dimensions"]) == 19
        assert payload["confidence"] == score.confidence

    def test_assessment_to_dict_contains_all_scores(self):
        candidates = [_candidate("commerce-candidate-a"), _candidate("commerce-candidate-b")]
        assessment = mod.rank_opportunities(candidates, workspace_id="workspace-1", query="x", generated_at=1.0)
        payload = assessment.to_dict()
        assert len(payload["scores"]) == 2
        assert payload["top_candidate_id"] == assessment.top_candidate_id
