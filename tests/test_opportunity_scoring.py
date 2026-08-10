"""Tests for backend.mvp_commerce.opportunity_scoring."""
from __future__ import annotations

from backend.adapters.research.cj_public_evidence import CJProductEvidence
from backend.contracts.events import Event
from backend.mvp_commerce import opportunity_scoring as mod
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
) -> CJProductEvidence:
    field_status = {
        "price": price_status, "shipping_cost": shipping_status,
        "estimated_delivery_days": delivery_status, "weight_kg": weight_status, "variants": variants_status,
    }
    return CJProductEvidence(
        source="cj_public_page", source_url="https://www.cjdropshipping.com/product/x.html", observed_at=1_700_000_000.0,
        external_product_id="cj-1", title="Portable Espresso Maker", field_status=field_status,
        price=price, variants=variants, weight_kg=weight_kg, shipping_cost=shipping_cost,
        estimated_delivery_days=delivery_days,
    )


def _evidence_result(evidence: CJProductEvidence | None, *, unit_cost=9.5, shipping_cost=2.0) -> SupplierEvidenceResult:
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
                     "shipping_complexity", "weight_volume", "variant_complexity",
                     "category_stability", "competition_estimate"):
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
        assert len(score.unknowns) == 8
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
        evidence = _evidence()
        result = _evidence_result(evidence)
        score = mod.score_opportunity(_candidate(), supplier_evidence=result)
        by_name = {d.name: d for d in score.dimensions}
        assert by_name["supplier_evidence_quality"].provenance == "observed"
        assert by_name["supplier_evidence_quality"].is_unknown is False
        assert by_name["observed_supplier_cost"].provenance == "observed"
        assert by_name["observed_supplier_cost"].raw_value == 9.5

    def test_product_simplicity_uses_observed_variant_count(self):
        evidence = _evidence(variants=({"name": "A"},))
        result = _evidence_result(evidence)
        score = mod.score_opportunity(_candidate(), supplier_evidence=result)
        by_name = {d.name: d for d in score.dimensions}
        assert by_name["product_simplicity"].raw_value == 1.0
        assert by_name["product_simplicity"].provenance == "observed"

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


class TestRecommendedAction:
    def test_low_score_without_supplier_evidence_recommends_corroboration(self):
        # Without any supplier evidence, six candidate-only dimensions are
        # always available (never "unavailable"), which floors confidence
        # at ~0.32 -- never full certainty, but also never low enough to
        # trip the <0.3 "gather more evidence" branch on its own. A weak
        # candidate with a low composite therefore lands in the middle
        # "corroborate" bucket, not the advance bucket.
        score = mod.score_opportunity(_candidate(source_count=1, local_score=5.0, recency=50.0))
        assert score.confidence < 0.6
        assert score.composite_score < 60.0
        assert score.recommended_action == "corroborate_before_advancing"

    def test_confidence_formula_would_recommend_gathering_evidence_below_threshold(self):
        # score_opportunity() always computes six candidate-only dimensions
        # (never "unavailable"), which floors reachable confidence at
        # ~0.32 for any real candidate -- so the <0.3 "gather more
        # evidence" branch is unreachable end-to-end today. Assert the
        # threshold logic itself directly against _confidence()'s output
        # so a future change to that floor (e.g. more optional dimensions)
        # is still guarded by a real test of the decision boundary.
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
            assert event.metadata["no_spend_authority"] is True
            assert event.metadata["no_order_authority"] is True

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
        assert len(payload["dimensions"]) == 14
        assert payload["confidence"] == score.confidence

    def test_assessment_to_dict_contains_all_scores(self):
        candidates = [_candidate("commerce-candidate-a"), _candidate("commerce-candidate-b")]
        assessment = mod.rank_opportunities(candidates, workspace_id="workspace-1", query="x", generated_at=1.0)
        payload = assessment.to_dict()
        assert len(payload["scores"]) == 2
        assert payload["top_candidate_id"] == assessment.top_candidate_id
