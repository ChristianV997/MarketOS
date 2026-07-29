"""Typed, vendor-neutral domain agents backed optionally by PydanticAI.

These agents analyze and validate commerce artifacts only. They do not receive
advertising, payment, fulfillment, or browser credentials; execution remains
owned by the existing MarketOS gates and loop.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Sequence

from pydantic import BaseModel, Field

from backend.contracts.adapters import AgentProvider
from backend.agents.pydantic_boundary import agent_provider
from backend.agents.marketos_read_tools import MarketOSReadTools, default_read_tools
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


class SupplierOfferInput(BaseModel):
    supplier_id: str = Field(min_length=1, max_length=200)
    unit_cost: float = Field(gt=0)
    shipping_cost: float = Field(default=0.0, ge=0.0)
    fulfillment_days: int | None = Field(default=None, ge=0)
    inventory_units: int | None = Field(default=None, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    source_ref: str = ""


class SupplierComparisonRequest(BaseModel):
    product_id: str = Field(min_length=1)
    offers: list[SupplierOfferInput] = Field(min_length=1, max_length=25)
    dry_run: bool = True


class SupplierComparisonResult(BaseModel):
    selected_supplier_id: str = ""
    rationale: str = ""
    risks: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class CreativeBriefRequest(BaseModel):
    product_id: str = Field(min_length=1)
    product_name: str = Field(min_length=1)
    platform: str = Field(min_length=1)
    audience: str = Field(default="", max_length=500)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)
    dry_run: bool = True


class CreativeBriefResult(BaseModel):
    product_id: str = ""
    brief: str = ""
    hooks: list[str] = Field(default_factory=list, max_length=10)
    angles: list[str] = Field(default_factory=list, max_length=10)
    claims_to_verify: list[str] = Field(default_factory=list, max_length=20)


class MetricsReconciliationRequest(BaseModel):
    campaign_id: str = Field(min_length=1)
    source_metrics: dict[str, float] = Field(default_factory=dict)
    source_refs: list[str] = Field(default_factory=list, max_length=20)
    dry_run: bool = True


class MetricsReconciliationResult(BaseModel):
    campaign_id: str = ""
    reconciled_metrics: dict[str, float] = Field(default_factory=dict)
    discrepancies: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


def _read_tools(tools: Sequence[Callable[..., Any]] | None) -> Sequence[Callable[..., Any]]:
    return default_read_tools() if tools is None else tools


def create_product_research_agent(*, provider: AgentProvider = agent_provider, tools: Sequence[Callable[..., Any]] | None = None) -> Any:
    return provider.create(
        name="product-research",
        instructions=(
            "Analyze provided MarketOS research evidence and return only a "
            "ProductResearchResult. Use only the supplied read-only MarketOS "
            "evidence tool when needed; do not invent evidence or perform actions."
        ),
        output_type=ProductResearchResult,
        tools=_read_tools(tools),
    )


def create_campaign_qa_agent(*, provider: AgentProvider = agent_provider, tools: Sequence[Callable[..., Any]] | None = None) -> Any:
    return provider.create(
        name="campaign-qa",
        instructions=(
            "Review the supplied campaign copy for policy and completeness. "
            "Return only CampaignQAResult. Never launch or publish anything."
        ),
        output_type=CampaignQAResult,
        tools=_read_tools(tools),
    )


def create_supplier_comparison_agent(*, provider: AgentProvider = agent_provider, tools: Sequence[Callable[..., Any]] | None = None) -> Any:
    return provider.create(
        name="supplier-comparison",
        instructions=(
            "Compare only the provided MarketOS supplier offers and return a "
            "SupplierComparisonResult. Do not contact suppliers, place orders, "
            "or invent logistics facts."
        ),
        output_type=SupplierComparisonResult,
        tools=_read_tools(tools),
    )


def create_creative_brief_agent(*, provider: AgentProvider = agent_provider, tools: Sequence[Callable[..., Any]] | None = None) -> Any:
    return provider.create(
        name="creative-brief",
        instructions=(
            "Create a factual CreativeBriefResult from the supplied MarketOS "
            "product evidence. Do not create ads, publish content, or claim "
            "unverified product capabilities."
        ),
        output_type=CreativeBriefResult,
        tools=_read_tools(tools),
    )


def create_metrics_reconciliation_agent(*, provider: AgentProvider = agent_provider, tools: Sequence[Callable[..., Any]] | None = None) -> Any:
    return provider.create(
        name="metrics-reconciliation",
        instructions=(
            "Reconcile only the supplied campaign metrics and return a "
            "MetricsReconciliationResult. Do not adjust budgets, launch ads, "
            "or fabricate missing measurements."
        ),
        output_type=MetricsReconciliationResult,
        tools=_read_tools(tools),
    )


async def _run_typed_agent(
    agent: Any,
    request: BaseModel,
    output_type: type[BaseModel],
    *,
    trace_name: str,
    evidence_query: str = "",
    **attributes: Any,
) -> BaseModel:
    with tracer.span(trace_name, workspace="commerce", source="pydantic-ai", dry_run=bool(getattr(request, "dry_run", True)), **attributes) as span:
        prompt = request.model_dump_json()
        # A live agent always receives a bounded read-only retrieval preflight
        # from the existing MarketOS skill registry. This gives the model
        # provenance-backed context even if it elects not to request the
        # supplied semantic_evidence tool again. Dry-runs stay retrieval-free.
        if not bool(getattr(request, "dry_run", True)) and evidence_query:
            try:
                evidence = MarketOSReadTools().semantic_evidence(evidence_query, top_k=3)
                if evidence:
                    prompt += "\nRegistered MarketOS evidence (read-only): " + json.dumps(evidence, sort_keys=True)
                    span.attributes["marketos_evidence_collections"] = len(evidence)
                    span.attributes["marketos_evidence_records"] = sum(len(hits) for hits in evidence.values())
            except Exception as exc:
                # Retrieval is useful evidence, not an execution authority.
                # Preserve the agent's bounded analysis path while recording
                # why contextual evidence was unavailable.
                span.attributes["marketos_evidence_error"] = type(exc).__name__
        result = await agent.run(prompt)
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
        return output if isinstance(output, output_type) else output_type.model_validate(output)


async def run_product_research(request: ProductResearchRequest, *, provider: AgentProvider = agent_provider) -> ProductResearchResult:
    return await _run_typed_agent(create_product_research_agent(provider=provider), request, ProductResearchResult, trace_name="agent.product_research", evidence_query=request.query)  # type: ignore[return-value]


async def run_campaign_qa(request: CampaignQARequest, *, provider: AgentProvider = agent_provider) -> CampaignQAResult:
    return await _run_typed_agent(create_campaign_qa_agent(provider=provider), request, CampaignQAResult, trace_name="agent.campaign_qa", evidence_query=f"{request.product_id} {request.creative_id} {request.platform}", platform=request.platform)  # type: ignore[return-value]


async def run_supplier_comparison(request: SupplierComparisonRequest, *, provider: AgentProvider = agent_provider) -> SupplierComparisonResult:
    return await _run_typed_agent(create_supplier_comparison_agent(provider=provider), request, SupplierComparisonResult, trace_name="agent.supplier_comparison", evidence_query=request.product_id)  # type: ignore[return-value]


async def run_creative_brief(request: CreativeBriefRequest, *, provider: AgentProvider = agent_provider) -> CreativeBriefResult:
    return await _run_typed_agent(create_creative_brief_agent(provider=provider), request, CreativeBriefResult, trace_name="agent.creative_brief", evidence_query=f"{request.product_name} {request.platform}", platform=request.platform)  # type: ignore[return-value]


async def run_metrics_reconciliation(request: MetricsReconciliationRequest, *, provider: AgentProvider = agent_provider) -> MetricsReconciliationResult:
    return await _run_typed_agent(create_metrics_reconciliation_agent(provider=provider), request, MetricsReconciliationResult, trace_name="agent.metrics_reconciliation", evidence_query=request.campaign_id)  # type: ignore[return-value]
