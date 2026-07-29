from backend.agents.pydantic_boundary import PydanticAIAgentProvider


def test_pydantic_agent_provider_is_optional():
    health = PydanticAIAgentProvider().health()
    assert health.name == "pydantic-ai"
    assert isinstance(health.configured, bool)
