"""Tests for build_opportunity_ranking_summaries — the decoded (not
key-list-only) view of opportunity_scoring_events() output, following the
same pattern as build_commerce_run_summaries/build_shopify_import_summaries."""
from __future__ import annotations

from backend.events.query_models import EventQuery
from backend.events.query_service import build_opportunity_ranking_summaries, event_query_report, query_events
from backend.mvp_commerce.models import OpportunityCandidate
from backend.mvp_commerce.opportunity_scoring import opportunity_scoring_events, rank_opportunities


def _candidate(candidate_id: str, local_score: float) -> OpportunityCandidate:
    return OpportunityCandidate(
        candidate_id, "workspace-1", "portable espresso maker", "Portable Espresso Maker", "public_signal_hypothesis",
        ("sig-1", "sig-2"), ("title one", "title two"), ("https://example.com/a",), 2, local_score, 100.0,
        "moderate", "low", ("Supplier cost is unverified.",), ("Demand is unverified.",),
        ("No demand or ROAS claim is supported.",), "Collect supplier, price, and customer-problem evidence manually.",
    )


def _events():
    strong = _candidate("commerce-candidate-strong", 90.0)
    weak = _candidate("commerce-candidate-weak", 20.0)
    assessment = rank_opportunities([weak, strong], workspace_id="workspace-1", query="portable espresso maker", generated_at=1_700_000_000.0)
    return opportunity_scoring_events(assessment, run_id="commerce-mvp-run-1"), assessment


class TestBuildOpportunityRankingSummaries:
    def test_summary_decodes_full_score_breakdown_not_just_keys(self):
        events, assessment = _events()
        summaries = build_opportunity_ranking_summaries(events)
        assert len(summaries) == 1
        summary = summaries[0]
        assert summary.workspace_id == "workspace-1"
        assert summary.run_id == "commerce-mvp-run-1"
        assert summary.query == "portable espresso maker"
        assert summary.top_candidate_id == assessment.top_candidate_id
        assert summary.candidate_count == 2
        # This is the point of this builder: real dimension/score data, not
        # the generic timeline's {"keys": [...], "item_count": N} redaction.
        first_score = summary.scores[0]
        assert first_score["candidate_id"] == assessment.top_candidate_id
        assert "dimensions" in first_score
        assert "composite_score" in first_score
        assert "confidence" in first_score
        assert "reasons" in first_score

    def test_scores_ordered_by_ranking_not_event_emission_order(self):
        events, assessment = _events()
        summaries = build_opportunity_ranking_summaries(events)
        ordered_ids = [score["candidate_id"] for score in summaries[0].scores]
        assert ordered_ids == [score.candidate_id for score in assessment.scores]

    def test_to_dict_is_json_safe(self):
        events, _ = _events()
        summary = build_opportunity_ranking_summaries(events)[0]
        payload = summary.to_dict()
        assert isinstance(payload["scores"], list)
        assert isinstance(payload["scores"][0], dict)

    def test_ignores_unrelated_events(self):
        from backend.contracts.events import Event

        events, _ = _events()
        unrelated = Event("evt-unrelated", "workspace-1", "commerce_mvp_run", "run-x", "commerce_mvp_run_started", 1, 1.0, source="x")
        summaries = build_opportunity_ranking_summaries([*events, unrelated])
        assert len(summaries) == 1

    def test_no_scoring_events_yields_no_summaries(self):
        assert build_opportunity_ranking_summaries([]) == []

    def test_event_query_report_includes_opportunity_rankings(self):
        events, _ = _events()
        query = EventQuery(workspace_id="workspace-1", limit=50)
        report = event_query_report(events, query)
        assert "opportunity_rankings" in report
        assert len(report["opportunity_rankings"]) == 1
        assert report["opportunity_rankings"][0]["candidate_count"] == 2

    def test_query_events_respects_limit_for_summary_grouping(self):
        events, _ = _events()
        query = EventQuery(workspace_id="workspace-1", limit=1)
        limited = query_events(events, query)
        assert len(limited) == 1
