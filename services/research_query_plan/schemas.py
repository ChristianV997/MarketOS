"""Contracts for offline localized product-research query planning.

A planned query is a search suggestion for human or offline tooling use.
It is never demand proof, supplier proof, live validation, or launch authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

PLAN_VERSION = "research-query-plan-v1"
SOURCE_FAMILIES = ("marketplace", "supplier", "consumer_attention")
BUYER_INTENTS = ("consumer", "business", "reseller", "unknown")
SUPPORTED_LANGUAGES = frozenset({"en", "es"})
MAX_QUERIES_PER_SOURCE = 5
MAX_TOTAL_QUERIES = 15
MAX_BRIEF_CHARS = 240


@dataclass(frozen=True)
class ProductResearchBrief:
    """Operator-supplied product brief. No provider URLs or CSV assembly required."""

    product_query: str
    category: str = ""
    region: str = ""
    language: str = "en"
    intended_buyer: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_query": self.product_query,
            "category": self.category,
            "region": self.region,
            "language": self.language,
            "intended_buyer": self.intended_buyer,
        }


@dataclass(frozen=True)
class PlannedQuery:
    query_text: str
    source_family: str
    rationale: str
    is_original: bool = False
    is_evidence: bool = False
    language_applied: str = "en"
    region_applied: str = ""
    tags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_text": self.query_text,
            "source_family": self.source_family,
            "rationale": self.rationale,
            "is_original": self.is_original,
            "is_evidence": False,
            "language_applied": self.language_applied,
            "region_applied": self.region_applied,
            "tags": list(self.tags),
        }


@dataclass(frozen=True)
class ResearchQueryPlan:
    plan_version: str
    brief: ProductResearchBrief
    queries: tuple[PlannedQuery, ...]
    flags: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    ok: bool = True
    live_validated: bool = False
    launch_authorized: bool = False
    authority: str = "query_planning_only"

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_version": self.plan_version,
            "brief": self.brief.to_dict(),
            "queries": [item.to_dict() for item in self.queries],
            "flags": list(self.flags),
            "limitations": list(self.limitations),
            "ok": self.ok,
            "live_validated": False,
            "launch_authorized": False,
            "authority": self.authority,
            "counts": {
                "total": len(self.queries),
                "per_source": {
                    family: len([q for q in self.queries if q.source_family == family])
                    for family in SOURCE_FAMILIES
                },
            },
        }


def coerce_brief(value: ProductResearchBrief | Mapping[str, Any]) -> ProductResearchBrief:
    if isinstance(value, ProductResearchBrief):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("brief must be ProductResearchBrief or mapping")
    return ProductResearchBrief(
        product_query=str(value.get("product_query") or value.get("query") or ""),
        category=str(value.get("category") or ""),
        region=str(value.get("region") or value.get("geography") or ""),
        language=str(value.get("language") or "en"),
        intended_buyer=str(value.get("intended_buyer") or value.get("buyer") or "unknown"),
    )


__all__ = [
    "BUYER_INTENTS",
    "MAX_BRIEF_CHARS",
    "MAX_QUERIES_PER_SOURCE",
    "MAX_TOTAL_QUERIES",
    "PLAN_VERSION",
    "PlannedQuery",
    "ProductResearchBrief",
    "ResearchQueryPlan",
    "SOURCE_FAMILIES",
    "SUPPORTED_LANGUAGES",
    "coerce_brief",
]
