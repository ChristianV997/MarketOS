from backend.optimization.optimization_registry import OptimizationRegistry
from backend.optimization.portfolio_actions import PortfolioActionSet
from backend.optimization.scenario import PortfolioOptimizationPlan


def test_optimization_registry_missing_corrupt_and_round_trip(tmp_path):
    path = tmp_path / "optimization.json"
    registry = OptimizationRegistry(path)
    assert registry.list_plans() == []
    path.write_text("bad", encoding="utf-8")
    assert OptimizationRegistry(path).list_action_sets() == []
    registry = OptimizationRegistry(path)
    action_set = PortfolioActionSet("set", "ws", "Actions", "Objective")
    plan = PortfolioOptimizationPlan("plan", "ws", "Plan", "Objective", "set")
    registry.register_action_set(action_set); registry.register_plan(plan)
    restored = OptimizationRegistry(path)
    assert restored.get_action_set("set").workspace_id == "ws"
    assert restored.latest_plan("ws").optimization_id == "plan"
