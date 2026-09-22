"""services.market_research — product-agnostic Market Research service.

Composes existing offline evidence authorities
(evaluation.commerce.marketplace_trends, .public_market_benchmark,
.supplier_feasibility, .consumer_attention, .opportunity_synthesis) into
one consulting-ready report. Creates no second scorer, ranking engine, or
promotion gate.
"""
from __future__ import annotations

from .report import REPORT_VERSION, TITLE, build_market_research_report, render_market_research_markdown
from .schemas import (
    DEFAULT_OFFERING_KIND,
    EVIDENCE_STATUSES,
    OFFERING_KINDS,
    EvidenceMatrixRow,
    MarketResearchRequest,
    MarketResearchResult,
    ValidationStep,
)

__all__ = [
    "REPORT_VERSION",
    "TITLE",
    "build_market_research_report",
    "render_market_research_markdown",
    "OFFERING_KINDS",
    "DEFAULT_OFFERING_KIND",
    "EVIDENCE_STATUSES",
    "MarketResearchRequest",
    "MarketResearchResult",
    "EvidenceMatrixRow",
    "ValidationStep",
]
