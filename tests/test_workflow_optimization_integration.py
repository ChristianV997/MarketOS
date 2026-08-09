from backend.workflows.orchestrator import run_workflow
from backend.workflows.runbook import get_workflow_runbook


def test_portfolio_optimization_workflow_stage_and_runbook_exist():
    assert "portfolio_optimization" in get_workflow_runbook("full_market_cycle").stages
    assert "portfolio_optimization" in get_workflow_runbook("portfolio_optimization_cycle").stages
    result = run_workflow("workflow-optimization-test", "portfolio_optimization_cycle", payload={}, stop_after_stage="portfolio_optimization")
    assert result["status"] in {"partial", "completed"}
    stage = next(x for x in result["stages"] if x["stage_name"] == "portfolio_optimization")
    assert stage["status"] in {"completed", "partial", "blocked"}
