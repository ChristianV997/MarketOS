"""services.research_query_plan — offline localized product-research query planning.

Turns a short operator brief (product/query, category, region, language,
intended buyer) into bounded, source-specific search variants for marketplace,
supplier, and consumer-attention research. Does not call providers, assemble
URLs/CSVs, score opportunities, or authorize launch.
"""
from .plan import build_research_query_plan
from .schemas import (
    BUYER_INTENTS,
    MAX_QUERIES_PER_SOURCE,
    MAX_TOTAL_QUERIES,
    PLAN_VERSION,
    PlannedQuery,
    ProductResearchBrief,
    ResearchQueryPlan,
    SOURCE_FAMILIES,
    SUPPORTED_LANGUAGES,
    coerce_brief,
)

__all__ = [
    "BUYER_INTENTS",
    "MAX_QUERIES_PER_SOURCE",
    "MAX_TOTAL_QUERIES",
    "PLAN_VERSION",
    "PlannedQuery",
    "ProductResearchBrief",
    "ResearchQueryPlan",
    "SOURCE_FAMILIES",
    "SUPPORTED_LANGUAGES",
    "build_research_query_plan",
    "coerce_brief",
]
