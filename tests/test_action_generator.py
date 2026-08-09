from backend.optimization.action_generator import generate_portfolio_actions


def test_action_generator_returns_safe_deduplicated_candidates():
    result = generate_portfolio_actions("action-generator-test", 200)
    assert len(result.actions) <= 200
    assert len({x.action_id for x in result.actions}) == len(result.actions)
    assert all(x.safe_endpoint == "" or x.safe_endpoint.startswith("/api/") for x in result.actions)
    assert all(x.metadata.get("simulated_only") is True for x in result.actions + result.blocked_actions)
