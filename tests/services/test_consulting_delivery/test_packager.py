import pytest
from services.consulting_delivery.packager import package_consulting_deliverable
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
    r2 = CommercialReport(
        report_id="r2", workspace_id="ws_2", proposal_id="p1", experiment_id="e1",
        service_name="test", title="R2", summary="Sum", findings="Find", recommendations=[],
        risk_flags=[], next_actions=[], metadata={}, status="ok"
    )

    pr1 = PortfolioReport(
        portfolio_report_id="pr1", workspace_id="ws_1", title="PR1", summary="Sum",
        report_ids=["r1"], service_counts={}, status_counts={}, top_recommendations=[],
        recurring_risk_flags=[], next_actions=[], metrics={}, metadata={}
    )

    registry.register(r1)
    registry.register(r2)
    registry.register_portfolio_report(pr1)

    return registry

def test_packager_accepts_reports_and_verifies_integrity(mock_registry):
    pkg = package_consulting_deliverable(
        workspace_id="ws_1",
        package_id="pkg_1",
        title="Consulting Test",
        objective="Obj",
        executive_summary="Exec",
        metadata={},
        report_ids=["r1"],
        portfolio_report_ids=["pr1"]
    )

    assert len(pkg.sections) == 2
    assert pkg.sections[0].title == "Commercial Report: R1"
    assert pkg.sections[1].title == "Portfolio Analysis: PR1"

def test_packager_rejects_missing_reports(mock_registry):
    with pytest.raises(ValueError, match="linked_report_missing"):
        package_consulting_deliverable(
            workspace_id="ws_1",
            package_id="pkg_1",
            title="Consulting Test",
            objective="Obj",
            executive_summary="Exec",
            metadata={},
            report_ids=["nonexistent"]
        )

def test_packager_rejects_cross_workspace_reports(mock_registry):
    with pytest.raises(ValueError, match="cross_workspace_leakage"):
        package_consulting_deliverable(
            workspace_id="ws_1",
            package_id="pkg_1",
            title="Consulting Test",
            objective="Obj",
            executive_summary="Exec",
            metadata={},
            report_ids=["r2"] # r2 belongs to ws_2
        )

def test_packager_enforces_bounded_output(mock_registry):
    # Update r1 findings to be massive
    r1 = mock_registry.get("r1")
    r1.findings = "X" * 600000
    mock_registry.register(r1)

    with pytest.raises(ValueError, match="bounded_output_exceeded"):
        package_consulting_deliverable(
            workspace_id="ws_1",
            package_id="pkg_1",
            title="Consulting Test",
            objective="Obj",
            executive_summary="Exec",
            metadata={},
            report_ids=["r1"]
        )
