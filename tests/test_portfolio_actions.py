from backend.optimization.portfolio_actions import PortfolioAction, PortfolioActionSet


def test_portfolio_actions_are_bounded_and_simulated_only():
    action = PortfolioAction("a", "ws", "acquire_evidence", "Evidence", "Import manually", estimated_cost=-1, total_action_score=999, safe_endpoint="/api/discovery/import-evidence", metadata={"simulated_only": True})
    action_set = PortfolioActionSet("set", "ws", "Actions", "Objective", [action])
    assert action.estimated_cost == 0
    assert action.total_action_score == 100
    assert action_set.from_dict(action_set.to_dict()).actions[0].action_id == "a"
    assert "No live budget" in action_set.to_markdown()
