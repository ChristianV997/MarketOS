from backend.optimization.portfolio_actions import PortfolioAction
from backend.optimization.scenario import OptimizationScenario, PortfolioOptimizationPlan, ResourceConstraint


def test_scenario_and_plan_serialize_simulated_constraints():
    constraint = ResourceConstraint("c", 100, 4, 2, "balanced", "low")
    scenario = OptimizationScenario("s", "ws", "Scenario", constraint)
    plan = PortfolioOptimizationPlan("p", "ws", "Plan", "Objective", "set", [scenario])
    restored = PortfolioOptimizationPlan.from_dict(plan.to_dict())
    assert restored.scenarios[0].constraint.budget == 100
    assert "simulated" in restored.to_markdown().lower()
