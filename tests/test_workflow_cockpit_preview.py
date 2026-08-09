from backend.workflows.runbook import get_workflow_runbook


def test_cockpit_preview_runbook_is_separate_from_full_cycle():
    assert get_workflow_runbook("cockpit_preview_cycle").stages == ["portfolio_optimization", "operating_plan", "execution_cockpit_preview", "final_summary"]
    assert "execution_cockpit_preview" not in get_workflow_runbook("full_market_cycle").stages
