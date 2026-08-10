"""Tests for build_competition_summaries — the decoded (not
key-list-only) view of competition_intelligence_events() output, following
the same pattern as build_commerce_run_summaries/build_opportunity_ranking_summaries."""
from __future__ import annotations

from unittest.mock import patch

from backend.adapters.research import competition_evidence as ce_mod
from backend.contracts.adapters import SidecarContext
from backend.contracts.events import Event
from backend.events.query_models import EventQuery
from backend.events.query_service import build_competition_summaries, event_query_report, query_events
from backend.mvp_commerce import competition_intelligence as mod
from backend.mvp_commerce.supplier_evidence import SupplierEvidenceResult

HTML = """<html><head><script type="application/ld+json">
{"@type": "Product", "name": "Portable Espresso Maker", "brand": {"name": "Acme"},
 "offers": {"price": "32.00", "priceCurrency": "USD", "availability": "InStock"}}
</script></head></html>"""


def _events():
    with patch.object(ce_mod, "_check_robots", return_value=None), patch.object(ce_mod, "_bounded_get", return_value=HTML):
        report = mod.gather_market_intelligence(
            "portable espresso maker", context=SidecarContext(dry_run=False),
            competitor_urls=["https://example.com/1"], generated_at=1_700_000_000.0,
        )
    evidence = SupplierEvidenceResult(attempted=True, unit_cost=9.5, shipping_cost=2.0, source_url="https://cj.example/x")
    margin = mod.compute_margin_intelligence("cand-1", supplier_evidence=evidence, market_report=report)
    opp_report = mod.build_market_opportunity_report("cand-1", "Portable Espresso Maker", supplier_evidence=evidence, market_report=report, margin=margin)
    return mod.competition_intelligence_events(report, margin, opp_report, workspace_id="workspace-1", run_id="commerce-mvp-run-1"), report, margin


class TestBuildCompetitionSummaries:
    def test_summary_decodes_full_market_data_not_just_keys(self):
        events, report, margin = _events()
        summaries = build_competition_summaries(events)
        assert len(summaries) == 1
        summary = summaries[0]
        assert summary.workspace_id == "workspace-1"
        assert summary.run_id == "commerce-mvp-run-1"
        assert summary.observed_competitor_count == report.observed_competitor_count
        assert summary.observed_median_price == report.observed_median_price
        assert summary.market_saturation == report.market_saturation
        assert len(summary.offers) == 1
        assert summary.margin is not None
        assert summary.margin["observed_gross_margin"] == margin.observed_gross_margin

    def test_ignores_unrelated_events(self):
        events, _, _ = _events()
        unrelated = Event("evt-unrelated", "workspace-1", "commerce_mvp_run", "run-x", "commerce_mvp_run_started", 1, 1.0, source="x")
        summaries = build_competition_summaries([*events, unrelated])
        assert len(summaries) == 1

    def test_no_competition_events_yields_no_summaries(self):
        assert build_competition_summaries([]) == []

    def test_to_dict_is_json_safe(self):
        events, _, _ = _events()
        summary = build_competition_summaries(events)[0]
        payload = summary.to_dict()
        assert isinstance(payload["offers"], list)
        assert isinstance(payload["offers"][0], dict)

    def test_event_query_report_includes_competition_summaries(self):
        events, _, _ = _events()
        query = EventQuery(workspace_id="workspace-1", limit=50)
        report = event_query_report(events, query)
        assert "competition_summaries" in report
        assert len(report["competition_summaries"]) == 1

    def test_summary_without_margin_event_has_none_margin(self):
        with patch.object(ce_mod, "_check_robots", return_value=None), patch.object(ce_mod, "_bounded_get", return_value=HTML):
            report = mod.gather_market_intelligence(
                "x", context=SidecarContext(dry_run=False), competitor_urls=["https://example.com/1"], generated_at=1.0,
            )
        events = mod.competition_intelligence_events(report, None, None, workspace_id="workspace-1", run_id="run-2")
        summaries = build_competition_summaries(events)
        assert summaries[0].margin is None

    def test_query_events_respects_limit_for_summary_grouping(self):
        events, _, _ = _events()
        query = EventQuery(workspace_id="workspace-1", limit=1)
        limited = query_events(events, query)
        assert len(limited) == 1
