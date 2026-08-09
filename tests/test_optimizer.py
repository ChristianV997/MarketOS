from backend.optimization.optimizer import optimize_actions_for_constraint
from backend.optimization.portfolio_actions import PortfolioAction
from backend.optimization.scenario import ResourceConstraint


def _action(name, cost, hours, info, kind="acquire_evidence"):
    return PortfolioAction(name, "ws", kind, name, name, estimated_cost=cost, estimated_hours=hours, expected_information_gain=info, total_action_score=info, metadata={"simulated_only": True})


def test_optimizer_enforces_budget_hours_count_and_blocked_actions():
    actions = [_action("cheap", 0, 1, 80), _action("costly", 100, 3, 90), _action("blocked", 0, 1, 100)]
    actions[2].blocked_reasons = ["missing_input"]; actions[2].status = "blocked"
    result = optimize_actions_for_constraint(actions, ResourceConstraint("zero", 0, 2, 1, "maximize_information_gain", "low"))
    assert result.selected_action_ids == ["cheap"]
    assert "blocked" in result.blocked_action_ids
    assert result.total_simulated_cost <= 0 and result.total_estimated_hours <= 2


def test_optimizer_is_deterministic_for_same_inputs():
    actions = [_action("b", 0, 1, 50), _action("a", 0, 1, 50)]
    constraint = ResourceConstraint("c", 0, 2, 2)
    assert optimize_actions_for_constraint(actions, constraint).selected_action_ids == optimize_actions_for_constraint(actions, constraint).selected_action_ids
