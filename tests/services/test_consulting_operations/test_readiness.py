import pytest
from services.consulting_operations.readiness import evaluate_consulting_readiness

def test_missing_intake_fields_blocked():
    report = evaluate_consulting_readiness({
        "client_id": "c1"
        # missing workspace, package, scope
    })
    assert report.readiness_status == "blocked"
    assert not report.safe_handoff_ready
    assert any("intake_validation_failed" in b for b in report.blockers)

def test_unknown_package_blocked():
    report = evaluate_consulting_readiness({
        "client_id": "c1",
        "workspace_id": "w1",
        "package_selection": "unsupported_magic_package",
        "scope_description": "We need help with a bunch of random things.",
        "evidence_coverage": {"has_data": True}
    })
    assert report.readiness_status == "blocked"
    assert "unknown_package_selection" in report.blockers

def test_insufficient_evidence_blocked():
    report = evaluate_consulting_readiness({
        "client_id": "c1",
        "workspace_id": "w1",
        "package_selection": "market_validation",
        "scope_description": "We need to validate the market for this product properly with all the steps.",
        "evidence_coverage": {"has_market_data": False}
    })
    assert report.readiness_status == "blocked"
    assert "insufficient_evidence_for_market_validation" in report.blockers

def test_scope_description_too_brief_blocked():
    report = evaluate_consulting_readiness({
        "client_id": "c1",
        "workspace_id": "w1",
        "package_selection": "strategy_review",
        "scope_description": "Review strategy.", # Too brief
        "evidence_coverage": {"has_data": True}
    })
    assert report.readiness_status == "blocked"
    assert "scope_description_too_brief" in report.blockers

def test_successful_readiness_evaluation():
    report = evaluate_consulting_readiness({
        "client_id": "c1",
        "workspace_id": "w1",
        "package_selection": "growth_audit",
        "scope_description": "We require a comprehensive growth audit spanning ad accounts, funnels, and retention curves.",
        "evidence_coverage": {"has_ad_data": True, "has_funnel_data": True}
    })
    assert report.readiness_status == "ready_for_delivery"
    assert report.safe_handoff_ready is True
    assert report.intake_complete is True
    assert not report.blockers

    assert report.effort_estimates["total_hours"] == 40
    assert report.revision_limits == 2
    assert "funnel_audit" in report.milestones

def test_deterministic_fingerprint():
    payload = {
        "client_id": "c1",
        "workspace_id": "w1",
        "package_selection": "growth_audit",
        "scope_description": "We require a comprehensive growth audit spanning ad accounts, funnels, and retention curves.",
        "evidence_coverage": {"has_ad_data": True, "has_funnel_data": True}
    }
    r1 = evaluate_consulting_readiness(payload)
    r2 = evaluate_consulting_readiness(payload)
    assert r1.compute_fingerprint() == r2.compute_fingerprint()
