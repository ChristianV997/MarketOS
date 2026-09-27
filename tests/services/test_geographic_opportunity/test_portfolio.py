"""Tests for services.geographic_opportunity.portfolio -- the duck-typed
adapter onto backend.organization.portfolio_report.build_portfolio_report.
No unmerged "opportunity discovery" branch is imported anywhere here or
in portfolio.py itself; this only proves this service's own reports can
be aggregated through the existing, merged portfolio authority.
"""
from backend.organization.portfolio_report import PortfolioReport
from services.geographic_opportunity.portfolio import (
    GeographicOpportunityPortfolioEntry,
    build_geographic_opportunity_portfolio,
)
from services.geographic_opportunity.report import build_geographic_opportunity_report

from .conftest import GENERATED_AT, build_goods_offer, build_service_offer, build_unknown_offer


class TestPortfolioEntryShape:
    def test_from_report_exposes_every_field_build_portfolio_report_reads(self):
        report = build_geographic_opportunity_report(build_goods_offer(), generated_at=GENERATED_AT)
        entry = GeographicOpportunityPortfolioEntry.from_report(report)
        # build_portfolio_report reads exactly these six attributes off
        # each entry (confirmed by reading
        # backend/organization/portfolio_report.py before writing this
        # adapter) -- this asserts the duck-typed shape directly.
        for attribute in ("report_id", "service_name", "status", "recommendations", "next_actions", "risk_flags"):
            assert hasattr(entry, attribute)
        assert entry.service_name == "geographic_opportunity"
        assert entry.status == report.status

    def test_rejects_a_non_report_object(self):
        import pytest

        with pytest.raises(TypeError):
            GeographicOpportunityPortfolioEntry.from_report(object())

    def test_report_id_is_deterministic_for_identical_inputs(self):
        report = build_geographic_opportunity_report(build_goods_offer(), generated_at=GENERATED_AT)
        first = GeographicOpportunityPortfolioEntry.from_report(report)
        second = GeographicOpportunityPortfolioEntry.from_report(report)
        assert first.report_id == second.report_id

    def test_blockers_surface_as_next_actions_not_silently_dropped(self):
        # An unknown-geography report's only content is its blocker --
        # the portfolio entry must still carry it forward as a next
        # action, not silently produce an empty portfolio contribution.
        report = build_geographic_opportunity_report(build_unknown_offer(), generated_at=GENERATED_AT)
        entry = GeographicOpportunityPortfolioEntry.from_report(report)
        assert any("geography_kind=unknown" in item for item in entry.next_actions)

    def test_high_and_blocked_risks_become_risk_flags(self):
        from services.geographic_opportunity.schemas import FieldEvidence

        offer = build_goods_offer(duty_rate=None, freight_duty_evidence=FieldEvidence(quality="missing"))
        report = build_geographic_opportunity_report(offer, generated_at=GENERATED_AT)
        entry = GeographicOpportunityPortfolioEntry.from_report(report)
        assert any(flag.startswith("freight_duty:blocked") for flag in entry.risk_flags)


class TestBuildGeographicOpportunityPortfolio:
    def test_aggregates_multiple_reports_into_one_portfolio_report(self):
        reports = [
            build_geographic_opportunity_report(build_goods_offer(candidate_id="cand-a"), generated_at=GENERATED_AT),
            build_geographic_opportunity_report(build_service_offer(candidate_id="cand-b"), generated_at=GENERATED_AT),
        ]
        portfolio = build_geographic_opportunity_portfolio("ws-geo-1", reports)
        assert isinstance(portfolio, PortfolioReport)
        assert portfolio.workspace_id == "ws-geo-1"
        assert portfolio.service_counts.get("geographic_opportunity") == 2

    def test_empty_report_list_produces_an_empty_portfolio(self):
        portfolio = build_geographic_opportunity_portfolio("ws-geo-2", [])
        assert portfolio.report_ids == []
        assert portfolio.metadata.get("status") == "empty"
