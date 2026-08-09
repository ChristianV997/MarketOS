from backend.workflows.runbook import get_workflow_runbook, list_workflow_runbooks
from backend.workflows.workflow_models import WorkflowRun, WorkflowStage
from backend.workflows.workflow_summary import build_workflow_summary


def test_runbooks_and_summary_expose_recovery_and_safety():
    assert {x.workflow_type for x in list_workflow_runbooks()} >= {"full_market_cycle", "executive_intelligence_cycle"}
    assert "Resume" in get_workflow_runbook("full_market_cycle").to_markdown()
    run = WorkflowRun("w", "ws", "custom_safe_cycle", "Title", "Objective", stages=[WorkflowStage("s", "x", 1, status="blocked")])
    summary = build_workflow_summary(run)
    assert summary["blocked_stages"] == ["x"]
    assert summary["recovery_options"]
