"""Tests for services.supplier_logistics_consulting_integration.portfolio."""
from backend.organization.portfolio_report import PortfolioReport
from services.supplier_logistics_consulting_integration.portfolio import (
    SupplierLogisticsPortfolioEntry,
    build_supplier_logistics_portfolio,
)

from .conftest import build_goods_offer, build_hybrid_offer, build_report, build_service_offer, build_unknown_offer


class TestSingleOfferPortfolio:
    def test_builds_a_workspace_scoped_portfolio_report(self, workspace):
        report = build_report(build_goods_offer())
        portfolio = build_supplier_logistics_portfolio(workspace.workspace_id, [report])
        assert isinstance(portfolio, PortfolioReport)
        assert portfolio.workspace_id == workspace.workspace_id
        assert portfolio.service_counts.get("supplier_logistics_research") == 1

    def test_a_report_with_no_blockers_counts_as_completed(self, workspace):
        report = build_report(build_goods_offer())
        portfolio = build_supplier_logistics_portfolio(workspace.workspace_id, [report])
        assert portfolio.status_counts.get("completed") == 1

    def test_an_unknown_offering_counts_as_blocked(self, workspace):
        report = build_report(build_unknown_offer())
        portfolio = build_supplier_logistics_portfolio(workspace.workspace_id, [report])
        assert portfolio.status_counts.get("blocked") == 1


class TestMultipleOffersPortfolio:
    def test_aggregates_goods_service_and_hybrid_offers_together(self, workspace):
        reports = [
            build_report(build_goods_offer(candidate_id="cand-1")),
            build_report(build_service_offer(candidate_id="cand-2")),
            build_report(build_hybrid_offer(candidate_id="cand-3")),
        ]
        portfolio = build_supplier_logistics_portfolio(workspace.workspace_id, reports)
        assert portfolio.service_counts["supplier_logistics_research"] == 3
        assert len(portfolio.report_ids) == 3

    def test_report_ids_are_deterministic_and_stable(self, workspace):
        report = build_report(build_goods_offer(candidate_id="cand-stable"))
        first = build_supplier_logistics_portfolio(workspace.workspace_id, [report])
        second = build_supplier_logistics_portfolio(workspace.workspace_id, [report])
        assert first.portfolio_report_id == second.portfolio_report_id
        assert first.report_ids == second.report_ids

    def test_risk_flags_surface_high_and_blocked_severities_only(self, workspace):
        report = build_report(build_unknown_offer())
        entry = SupplierLogisticsPortfolioEntry.from_report(report)
        # An unknown offering has an empty risk_matrix (nothing to grade),
        # so risk_flags is empty -- it is not fabricated from the blocker text.
        assert entry.risk_flags == ()


class TestEmptyPortfolio:
    def test_empty_reports_produce_an_empty_but_valid_portfolio(self, workspace):
        portfolio = build_supplier_logistics_portfolio(workspace.workspace_id, [])
        assert portfolio.report_ids == []
        assert portfolio.metadata["status"] == "empty"
