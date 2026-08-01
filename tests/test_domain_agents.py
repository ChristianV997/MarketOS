import pytest
import asyncio

from backend.agents.domain_agents import (
    CampaignQARequest, CampaignQAResult, ProductResearchRequest, ProductResearchResult,
    CreativeBriefRequest, CreativeBriefResult, MetricsReconciliationRequest, MetricsReconciliationResult,
    SupplierComparisonRequest, SupplierComparisonResult,
    create_campaign_qa_agent, create_creative_brief_agent, create_metrics_reconciliation_agent,
    create_product_research_agent, create_supplier_comparison_agent,
)


class Provider:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return object()


def test_domain_agents_are_typed_and_use_one_provider_boundary():
    provider = Provider()
    create_product_research_agent(provider=provider)
    create_campaign_qa_agent(provider=provider)
    create_supplier_comparison_agent(provider=provider)
    create_creative_brief_agent(provider=provider)
    create_metrics_reconciliation_agent(provider=provider)
    assert provider.calls[0]["output_type"] is ProductResearchResult
    assert provider.calls[1]["output_type"] is CampaignQAResult
    assert provider.calls[2]["output_type"] is SupplierComparisonResult
    assert provider.calls[3]["output_type"] is CreativeBriefResult
    assert provider.calls[4]["output_type"] is MetricsReconciliationResult
    assert all(call["tools"][0].__name__ == "semantic_evidence" for call in provider.calls)
    assert ProductResearchRequest(query="mugs").dry_run is True
    assert CampaignQARequest(product_id="p", creative_id="c", platform="meta", copy_text="Buy").dry_run is True
    assert SupplierComparisonRequest(product_id="p", offers=[{"supplier_id": "s", "unit_cost": 2}]).dry_run is True
    assert CreativeBriefRequest(product_id="p", product_name="Mug", platform="meta").dry_run is True
    assert MetricsReconciliationRequest(campaign_id="c").dry_run is True


def test_domain_agent_requests_reject_empty_execution_inputs():
    with pytest.raises(Exception):
        ProductResearchRequest(query="")
    with pytest.raises(Exception):
        CampaignQARequest(product_id="", creative_id="c", platform="meta", copy_text="Buy")
    with pytest.raises(Exception):
        SupplierComparisonRequest(product_id="p", offers=[])


def test_domain_agent_runners_validate_mocked_provider_results():
    class Result:
        def __init__(self, data):
            self.data = data

    class Agent:
        def __init__(self, data):
            self.data = data
        async def run(self, _prompt):
            return Result(self.data)

    class RunnerProvider:
        def create(self, *, name, instructions, output_type, tools=()):
            if name == "product-research":
                return Agent({"product_name": "Mug", "confidence": 0.8})
            if name == "campaign-qa":
                return Agent({"approved": True, "policy_checks": {"copy": True}})
            if name == "supplier-comparison":
                return Agent({"selected_supplier_id": "supplier-a", "confidence": 0.7})
            if name == "creative-brief":
                return Agent({"product_id": "p", "brief": "Focus on portability", "hooks": ["Carry less"]})
            if name == "metrics-reconciliation":
                return Agent({"campaign_id": "c", "reconciled_metrics": {"spend": 10.0}, "confidence": 0.9})
            raise AssertionError(f"unexpected agent {name}")

    from backend.agents.domain_agents import run_campaign_qa, run_product_research, run_supplier_comparison, run_creative_brief, run_metrics_reconciliation
    research = asyncio.run(run_product_research(ProductResearchRequest(query="mugs"), provider=RunnerProvider()))
    qa = asyncio.run(run_campaign_qa(CampaignQARequest(product_id="p", creative_id="c", platform="meta", copy_text="Buy"), provider=RunnerProvider()))
    supplier = asyncio.run(run_supplier_comparison(SupplierComparisonRequest(product_id="p", offers=[{"supplier_id": "supplier-a", "unit_cost": 2}],), provider=RunnerProvider()))
    brief = asyncio.run(run_creative_brief(CreativeBriefRequest(product_id="p", product_name="Mug", platform="meta"), provider=RunnerProvider()))
    metrics = asyncio.run(run_metrics_reconciliation(MetricsReconciliationRequest(campaign_id="c", source_metrics={"spend": 10}), provider=RunnerProvider()))
    assert research.product_name == "Mug"
    assert research.confidence == 0.8
    assert qa.approved is True
    assert supplier.selected_supplier_id == "supplier-a"
    assert brief.hooks == ["Carry less"]
    assert metrics.reconciled_metrics["spend"] == 10.0
    from backend.observability.tracing import tracer
    names = {trace.name for trace in tracer.recent_traces()}
    assert {"agent.supplier_comparison", "agent.creative_brief", "agent.metrics_reconciliation"}.issubset(names)


def test_domain_agent_runners_emit_marketos_trace():
    class Result:
        data = {"product_name": "Mug", "confidence": 0.8}
    class Agent:
        async def run(self, _prompt):
            return Result()
    class Provider:
        def create(self, **_kwargs):
            return Agent()
    from backend.agents.domain_agents import run_product_research
    from backend.observability.tracing import tracer
    asyncio.run(run_product_research(ProductResearchRequest(query="mugs"), provider=Provider()))
    assert any(trace.name == "agent.product_research" for trace in tracer.recent_traces())


def test_marketos_read_tool_reuses_registered_semantic_search_and_bounds_evidence():
    from backend.agents.marketos_read_tools import MarketOSReadTools

    class Registry:
        def __init__(self):
            self.calls = []

        def execute(self, name, payload):
            self.calls.append((name, payload))
            return {"result": {"products": [{
                "record_id": "product-1", "score": 0.9,
                "payload": {"name": "Travel Mug", "url": "https://supplier.example/mug", "token": "not-exposed"},
            }]}}

    registry = Registry()
    result = MarketOSReadTools(registry).semantic_evidence("mug", top_k=99)
    assert registry.calls == [("semantic_search", {"query": "mug", "top_k": 10})]
    assert result["products"][0]["evidence"] == {
        "name": "Travel Mug", "url": "https://supplier.example/mug",
    }


def test_live_domain_agent_preflights_the_registered_read_tool(monkeypatch):
    from backend.agents import domain_agents

    calls = []

    class ReadTools:
        def semantic_evidence(self, query, top_k):
            calls.append((query, top_k))
            return {"products": [{"record_id": "p1", "score": 0.9, "evidence": {"name": "Mug"}}]}

    class Result:
        data = {"product_name": "Mug", "confidence": 0.8}

    class Agent:
        def __init__(self):
            self.prompt = ""

        async def run(self, prompt):
            self.prompt = prompt
            return Result()

    agent = Agent()

    class Provider:
        def create(self, **_kwargs):
            return agent

    monkeypatch.setattr(domain_agents, "MarketOSReadTools", lambda: ReadTools())
    result = asyncio.run(domain_agents.run_product_research(
        ProductResearchRequest(query="mug", dry_run=False), provider=Provider(),
    ))
    assert result.product_name == "Mug"
    assert calls == [("mug", 3)]
    assert "Registered MarketOS evidence" in agent.prompt
