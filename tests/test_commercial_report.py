from backend.organization.commercial_report import build_report_from_execution
from backend.governance.proposal import Proposal


def test_report_from_success_has_supported_content():
    proposal = Proposal(proposal_id="p-report", workspace_id="w", service_name="product_research", title="Audit")
    report = build_report_from_execution(proposal, {"service_name": "product_research", "status": "completed", "dry_run": True, "output": {"recommendation": "investigate", "next_actions": ["Validate demand"], "provenance": {"market_data": "not_connected"}}})
    assert report.status == "completed"
    assert "investigate" in report.recommendations
    assert "Validate demand" in report.next_actions
    assert "market data" not in report.summary.lower()


def test_report_from_unavailable_is_blocked_and_markdown_is_explicit():
    proposal = Proposal(proposal_id="p-blocked", workspace_id="w", service_name="customer_intelligence", title="ICP")
    report = build_report_from_execution(proposal, {"service_name": "customer_intelligence", "status": "service_module_unavailable", "blocked_reasons": ["service_module_unavailable"], "dry_run": True})
    assert report.status == "unavailable"
    assert "service_module_unavailable" in report.risk_flags
    assert "no commercial conclusion" in report.to_markdown()
