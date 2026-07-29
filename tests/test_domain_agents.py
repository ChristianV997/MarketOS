import pytest

from backend.agents.domain_agents import (
    CampaignQARequest, CampaignQAResult, ProductResearchRequest, ProductResearchResult,
    create_campaign_qa_agent, create_product_research_agent,
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
    assert provider.calls[0]["output_type"] is ProductResearchResult
    assert provider.calls[1]["output_type"] is CampaignQAResult
    assert ProductResearchRequest(query="mugs").dry_run is True
    assert CampaignQARequest(product_id="p", creative_id="c", platform="meta", copy_text="Buy").dry_run is True


def test_domain_agent_requests_reject_empty_execution_inputs():
    with pytest.raises(Exception):
        ProductResearchRequest(query="")
    with pytest.raises(Exception):
        CampaignQARequest(product_id="", creative_id="c", platform="meta", copy_text="Buy")
