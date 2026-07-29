"""Typed, vendor-neutral domain agents backed optionally by PydanticAI.

These agents analyze and validate commerce artifacts only. They do not receive
advertising, payment, fulfillment, or browser credentials; execution remains
owned by the existing MarketOS gates and loop.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.contracts.adapters import AgentProvider
from backend.agents.pydantic_boundary import agent_provider
from backend.observability.tracing import tracer


class ProductResearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    source_refs: list[str] = Field(default_factory=list, max_length=20)
    dry_run: bool = True


class ProductResearchResult(BaseModel):
    product_name: str = Field(min_length=1)
    product_id: str = ""
    rationale: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class CampaignQARequest(BaseModel):
    product_id: str = Field(min_length=1)
    creative_id: str = Field(min_length=1)
    platform: str = Field(min_length=1)
    copy_text: str = Field(min_length=1, max_length=10_000)
    dry_run: bool = True


class CampaignQAResult(BaseModel):
    approved: bool = False
    issues: list[str] = Field(default_factory=list)
    policy_checks: dict[str, bool] = Field(default_factory=dict)


def create_product_research_agent(*, provider: AgentProvider = agent_provider) -> Any:
    return provider.create(
        name="product-research",
        instructions=(
            "Analyze provided MarketOS research evidence and return only a "
            "ProductResearchResult. Do not invent evidence or perform actions."
        ),
        output_type=ProductResearchResult,
    )


def create_campaign_qa_agent(*, provider: AgentProvider = agent_provider) -> Any:
    return provider.create(
        name="campaign-qa",
        instructions=(
            "Review the supplied campaign copy for policy and completeness. "
            "Return only CampaignQAResult. Never launch or publish anything."
        ),
        output_type=CampaignQAResult,
    )


async def run_product_research(request: ProductResearchRequest, *, provider: AgentProvider = agent_provider) -> ProductResearchResult:
    agent = create_product_research_agent(provider=provider)
    with tracer.span("agent.product_research", workspace="commerce", source="pydantic-ai", dry_run=request.dry_run) as span:
        result = await agent.run(request.model_dump_json())
        output = getattr(result, "output", getattr(result, "data", result))
        usage = getattr(result, "usage", None)
        if callable(usage):
            try:
                usage = usage()
            except Exception:
                usage = None
        if isinstance(usage, dict):
            for key in ("total_tokens", "prompt_tokens", "completion_tokens", "cost", "cost_usd"):
                if key in usage:
                    span.attributes[f"usage.{key}"] = usage[key]
        return output if isinstance(output, ProductResearchResult) else ProductResearchResult.model_validate(output)


async def run_campaign_qa(request: CampaignQARequest, *, provider: AgentProvider = agent_provider) -> CampaignQAResult:
    agent = create_campaign_qa_agent(provider=provider)
    with tracer.span("agent.campaign_qa", workspace="commerce", source="pydantic-ai", dry_run=request.dry_run, platform=request.platform) as span:
        result = await agent.run(request.model_dump_json())
        output = getattr(result, "output", getattr(result, "data", result))
        usage = getattr(result, "usage", None)
        if callable(usage):
            try:
                usage = usage()
            except Exception:
                usage = None
        if isinstance(usage, dict):
            for key in ("total_tokens", "prompt_tokens", "completion_tokens", "cost", "cost_usd"):
                if key in usage:
                    span.attributes[f"usage.{key}"] = usage[key]
        return output if isinstance(output, CampaignQAResult) else CampaignQAResult.model_validate(output)
