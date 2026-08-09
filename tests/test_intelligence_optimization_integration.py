from backend.optimization.optimizer import build_portfolio_optimization_plan
from backend.intelligence.executive_brief_engine import build_executive_brief
from backend.intelligence.strategic_priority_engine import build_strategic_priority_plan


def test_intelligence_exposes_simulated_optimization_context():
    plan = build_portfolio_optimization_plan("intelligence-optimization-test")
    priority = build_strategic_priority_plan("intelligence-optimization-test")
    brief = build_executive_brief("intelligence-optimization-test", include_html=False)["brief"]
    assert priority.metadata.get("optimization_plan_id") == plan.optimization_id
    assert brief["metadata"]["optimization_plan_id"] == plan.optimization_id
    assert brief["metadata"]["simulated_budget_assumptions"]
