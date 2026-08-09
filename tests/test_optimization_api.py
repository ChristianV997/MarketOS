from api.routes.optimization import generate, latest, portfolio, scenario


def test_optimization_api_returns_safe_json_structures():
    generated = generate({"workspace_id": "optimization-api-test", "max_actions": 5})
    assert generated["simulated_only"] is True
    assert len(generated["action_set"]["actions"]) <= 5
    plan = portfolio({"workspace_id": "optimization-api-test", "constraints": [{"constraint_id": "c", "budget": 0, "hours": 2, "max_actions": 2, "objective": "maximize_information_gain"}]})
    assert plan["simulated_only"] is True
    assert scenario({"workspace_id": "optimization-api-test", "constraint": {"constraint_id": "c2", "budget": 0, "hours": 1, "max_actions": 1}})["simulated_only"] is True
    assert latest("optimization-api-test")["plan"]
