from pathlib import Path

from backend.optimization.optimization_registry import OptimizationRegistry
from backend.optimization.portfolio_actions import PortfolioAction, PortfolioActionSet
from backend.optimization.scenario import PortfolioOptimizationPlan
from backend.operations import operating_plan_builder as builder


def test_plan_maps_actions_dependencies_and_caps(monkeypatch, tmp_path):
    action1 = PortfolioAction("a1", "default", "run_refinement_cycle", "Refine", "refine", estimated_hours=2, total_action_score=80, safe_endpoint="/api/discovery/refinement-cycle")
    action2 = PortfolioAction("a2", "default", "refresh_pipeline", "Refresh", "refresh", estimated_hours=2, total_action_score=70)
    aset = PortfolioActionSet("as1", "default", "Actions", "objective", [action1, action2])
    plan = PortfolioOptimizationPlan("op1", "default", "Plan", "objective", "as1", recommended_actions=[action1, action2])
    reg = OptimizationRegistry(tmp_path / "opt.json"); reg.register_action_set(aset); reg.register_plan(plan)
    monkeypatch.setattr(builder, "get_optimization_registry", lambda: reg)
    result = builder.build_operating_plan_from_optimization(max_tasks=1, daily_hour_capacity=2)
    assert len(result.tasks) == 1
    assert result.tasks[0].checklist
    assert result.metadata["planning_only"] is True


def test_initial_plan_exists_without_optimization(monkeypatch, tmp_path):
    reg = OptimizationRegistry(tmp_path / "empty.json")
    monkeypatch.setattr(builder, "get_optimization_registry", lambda: reg)
    plan = builder.build_operating_plan_from_optimization()
    assert plan.metadata["setup_plan"] is True
    assert plan.tasks
