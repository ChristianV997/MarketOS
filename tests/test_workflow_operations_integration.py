from backend.workflows.runbook import get_workflow_runbook


def test_operating_cycle_runbook_and_full_cycle_stage():
    assert "operating_plan" in get_workflow_runbook("full_market_cycle").stages
    assert get_workflow_runbook("operating_cycle").stages == ["portfolio_optimization", "operating_plan", "executive_intelligence", "final_summary"]
