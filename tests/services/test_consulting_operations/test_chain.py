import pytest
from services.consulting_operations.chain import run_consulting_chain
from backend.organization.report_registry import get_report_registry
from backend.organization.commercial_report import CommercialReport
from backend.organization.portfolio_report import PortfolioReport

@pytest.fixture
def mock_registry(monkeypatch):
    registry = get_report_registry()
    registry.reports.clear()
    registry.portfolio_reports.clear()

    r1 = CommercialReport(
        report_id="r1", workspace_id="ws_1", proposal_id="p1", experiment_id="e1",
        service_name="test", title="R1", summary="Sum", findings="Find", recommendations=[],
        risk_flags=[], next_actions=[], metadata={}, status="ok"
    )

    pr1 = PortfolioReport(
        portfolio_report_id="pr1", workspace_id="ws_1", title="PR1", summary="Sum",
        report_ids=["r1"], service_counts={}, status_counts={}, top_recommendations=[],
        recurring_risk_flags=[], next_actions=[], metrics={}, metadata={}
    )

    registry.register(r1)
    registry.register_portfolio_report(pr1)

    return registry


def test_chain_successful_delivery(mock_registry):
    intake = {
        "client_id": "c1",
        "workspace_id": "ws_1",
        "package_selection": "growth_audit",
        "scope_description": "We require a comprehensive growth audit spanning ad accounts, funnels, and retention curves.",
        "evidence_coverage": {"has_ad_data": True, "has_funnel_data": True}
    }

    report = run_consulting_chain(
        intake_payload=intake,
        catalog_offers=["growth_audit", "market_validation"],
        report_ids=["r1"],
        portfolio_report_ids=["pr1"],
        economics_payload={"workspace_id": "ws_1", "fee": 5000, "evidence_status": "verified"}
    )

    assert report.status == "ready_for_delivery"
    assert report.deliverable is not None
    assert len(report.invalid_catalog_ids) == 0
    assert len(report.envelope_mismatches) == 0
    assert len(report.stale_evidence) == 0


def test_chain_invalid_catalog_id():
    intake = {
        "client_id": "c1",
        "workspace_id": "ws_1",
        "package_selection": "unsupported_audit",
        "scope_description": "We require a comprehensive growth audit spanning ad accounts, funnels, and retention curves.",
        "evidence_coverage": {"has_ad_data": True, "has_funnel_data": True}
    }

    report = run_consulting_chain(
        intake_payload=intake,
        catalog_offers=["growth_audit", "market_validation"],
        report_ids=[],
        portfolio_report_ids=[],
    )

    assert report.status == "blocked"
    assert "unsupported_audit" in report.invalid_catalog_ids


def test_chain_envelope_workspace_mismatch():
    intake = {
        "client_id": "c1",
        "workspace_id": "ws_1",
        "package_selection": "growth_audit",
        "scope_description": "We require a comprehensive growth audit spanning ad accounts, funnels, and retention curves.",
        "evidence_coverage": {"has_ad_data": True, "has_funnel_data": True}
    }

    report = run_consulting_chain(
        intake_payload=intake,
        catalog_offers=["growth_audit", "market_validation"],
        report_ids=[],
        portfolio_report_ids=[],
        economics_payload={"workspace_id": "ws_2", "fee": 5000}
    )

    assert report.status == "blocked"
    assert any("economics_workspace_mismatch" in e for e in report.envelope_mismatches)


def test_chain_scalar_economics_as_ranges():
    intake = {
        "client_id": "c1",
        "workspace_id": "ws_1",
        "package_selection": "growth_audit",
        "scope_description": "We require a comprehensive growth audit spanning ad accounts, funnels, and retention curves.",
        "evidence_coverage": {"has_ad_data": True, "has_funnel_data": True}
    }

    report = run_consulting_chain(
        intake_payload=intake,
        catalog_offers=["growth_audit", "market_validation"],
        report_ids=[],
        portfolio_report_ids=[],
        economics_payload={"workspace_id": "ws_1", "fee": {"min": 4000, "max": 6000}} # ranges should be rejected
    )

    assert report.status == "blocked"
    assert "scalar_economics_accidentally_accepted_as_ranges" in report.envelope_mismatches

def test_chain_stale_evidence():
    intake = {
        "client_id": "c1",
        "workspace_id": "ws_1",
        "package_selection": "growth_audit",
        "scope_description": "We require a comprehensive growth audit spanning ad accounts, funnels, and retention curves.",
        "evidence_coverage": {"has_ad_data": True, "has_funnel_data": True}
    }

    report = run_consulting_chain(
        intake_payload=intake,
        catalog_offers=["growth_audit", "market_validation"],
        report_ids=[],
        portfolio_report_ids=[],
        economics_payload={"workspace_id": "ws_1", "fee": 5000, "evidence_status": "stale"}
    )

    assert report.status == "blocked"
    assert "stale" in report.stale_evidence
