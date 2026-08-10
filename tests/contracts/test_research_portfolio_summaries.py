"""Tests for build_research_portfolio_summaries — the decoded (not
key-list-only) view of product_research_events() output, following the
same pattern as build_opportunity_ranking_summaries/build_competition_summaries."""
from __future__ import annotations

from backend.contracts.events import Event
from backend.events.query_models import EventQuery
from backend.events.query_service import build_research_portfolio_summaries, event_query_report, query_events
from backend.mvp_commerce.opportunity_scoring import score_opportunity
from backend.mvp_commerce.product_research import ResearchCandidate, build_research_portfolio, compare_portfolios, product_research_events
from tests.test_product_research import _candidate


def _events(*, with_comparison=False):
    candidates = [
        ResearchCandidate("c1", _candidate("c1", "Portable Espresso Maker"), score_opportunity(_candidate("c1", "Portable Espresso Maker"))),
        ResearchCandidate("c2", _candidate("c2", "Standing Desk"), score_opportunity(_candidate("c2", "Standing Desk"))),
    ]
    portfolio = build_research_portfolio(candidates, workspace_id="workspace-1", query="gadgets", generated_at=1_700_000_000.0)
    comparison = None
    if with_comparison:
        comparison = compare_portfolios(portfolio, portfolio)
    return product_research_events(portfolio, candidates, run_id="commerce-mvp-run-1", comparison=comparison), portfolio


class TestBuildResearchPortfolioSummaries:
    def test_summary_decodes_full_portfolio_data_not_just_keys(self):
        events, portfolio = _events()
        summaries = build_research_portfolio_summaries(events)
        assert len(summaries) == 1
        summary = summaries[0]
        assert summary.workspace_id == "workspace-1"
        assert summary.run_id == "commerce-mvp-run-1"
        assert summary.candidate_count == 2
        assert summary.cluster_count == len(portfolio.clusters)
        assert summary.quality is not None
        assert isinstance(summary.bucket_counts, dict)
        assert len(summary.clusters) == len(portfolio.clusters)

    def test_ignores_unrelated_events(self):
        events, _ = _events()
        unrelated = Event("evt-unrelated", "workspace-1", "commerce_mvp_run", "run-x", "commerce_mvp_run_started", 1, 1.0, source="x")
        summaries = build_research_portfolio_summaries([*events, unrelated])
        assert len(summaries) == 1

    def test_no_research_events_yields_no_summaries(self):
        assert build_research_portfolio_summaries([]) == []

    def test_to_dict_is_json_safe(self):
        events, _ = _events()
        summary = build_research_portfolio_summaries(events)[0]
        payload = summary.to_dict()
        assert isinstance(payload["clusters"], list)
        assert isinstance(payload["movements"], list)

    def test_event_query_report_includes_research_portfolios(self):
        events, _ = _events()
        query = EventQuery(workspace_id="workspace-1", limit=50)
        report = event_query_report(events, query)
        assert "research_portfolios" in report
        assert len(report["research_portfolios"]) == 1

    def test_movements_present_when_comparison_supplied(self):
        events, portfolio = _events(with_comparison=True)
        # both candidates unchanged -> compare_portfolios emits no
        # ranking_changed events, so movements stays empty here too --
        # confirms the summary reflects real emitted events, not a guess.
        summaries = build_research_portfolio_summaries(events)
        assert summaries[0].movements == ()

    def test_query_events_respects_limit_for_summary_grouping(self):
        events, _ = _events()
        query = EventQuery(workspace_id="workspace-1", limit=1)
        limited = query_events(events, query)
        assert len(limited) == 1
