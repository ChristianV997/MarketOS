from backend.agents.pydantic_boundary import PydanticAIAgentProvider


def test_pydantic_agent_provider_is_optional():
    health = PydanticAIAgentProvider().health()
    assert health.name == "pydantic-ai"
    assert isinstance(health.configured, bool)


def test_pydantic_provider_passes_only_explicit_read_tools(monkeypatch):
    import sys
    from types import SimpleNamespace

    captured = {}

    class Agent:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setitem(sys.modules, "pydantic_ai", SimpleNamespace(Agent=Agent))

    def semantic_evidence(query: str):
        return {"query": query}

    agent = PydanticAIAgentProvider().create(
        name="research", instructions="read only", output_type=dict, tools=(semantic_evidence,),
    )
    assert captured["tools"] == [semantic_evidence]
    assert agent.marketos_agent_name == "research"
