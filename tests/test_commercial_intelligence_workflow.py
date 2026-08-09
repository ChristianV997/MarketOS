from backend.workflows.runbook import get_workflow_runbook


def test_commercial_intelligence_workflow_is_present():
    stages=get_workflow_runbook("commercial_intelligence_cycle").stages
    assert "commercial_intelligence" in stages
