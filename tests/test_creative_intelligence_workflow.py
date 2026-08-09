from backend.workflows.runbook import get_workflow_runbook

def test_creative_intelligence_cycle_runbook_is_draft_only():
    stages=get_workflow_runbook("creative_intelligence_cycle").stages
    assert stages[:2]==["commercial_intelligence","creative_intelligence"]
    assert "validation_sprint" not in stages
