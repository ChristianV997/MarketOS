"""backend.adapters.research.tiktok_research_evidence — thin offline bridge.

Delegates to ``evaluation.commerce.tiktok_research_evidence``. No live TikTok
transport, credentials, scraping, or second organic adapter. Research Tools FAQ
blocks commercial users for Research Tools; Commercial Content API is evaluated
separately (EU-phase ad geography; Mexico not listed) and must not be assumed to
share the Research API eligibility rule without primary evidence. Creative Center
website visibility is not scrape permission; Marketing API own-account metrics
are not market-wide attention evidence.

Ordinary runtime returns a precise blocked/unavailable capability with zero
evidence rows. Fixture/fake offline demos require explicit
``allow_offline_demo=True`` and never count as operational capability.

Does not register in ``ResearchAdapterRegistry`` (trend-source adapters only).
Does not edit ``backend.adapters.tiktok_organic`` or TikTok API routes.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.contracts.adapters import AdapterHealth, SidecarContext
from evaluation.commerce.tiktok_research_evidence import (
    ACCESS_DATE,
    DOC_RECHECK_DATE,
    REPORT_VERSION,
    SOURCE,
    FakeTikTokResearchTransport,
    TikTokResearchEvidenceReport,
    TikTokResearchTransport,
    build_tiktok_research_evidence,
    official_citations,
    render_markdown,
    research_tool_capabilities,
)

_log = logging.getLogger(__name__)

DEFAULT_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "tiktok_research_evidence"
    / "sanitized_creative_snapshot.json"
)

EVIDENCE_TIER = "supplemental_non_live_attention"
MAX_RETRY_ATTEMPTS = 0

_LIVE_PREREQUISITES = (
    "TikTok Research Tools eligibility for MarketOS commercial use (FAQ: commercial users No)",
    "official Creative Center/Marketing API commercial-attention contract (absent)",
    "Approval Ledger provider_call approval",
    "credential reference only (no secret values in repo)",
    "terms/privacy and output-contract review",
    "separately reviewed live transport implementation",
)


@dataclass(frozen=True)
class TikTokResearchBridgeEvidence:
    """Bridge-shaped observation for product-research attachment."""

    source: str
    observed_at: float
    query: str
    status: str
    evidence_count: int
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    report: dict[str, Any] = dataclass_field(default_factory=dict)
    evidence_tier: str = EVIDENCE_TIER
    retry_attempts_allowed: int = MAX_RETRY_ATTEMPTS
    commercial_eligible: bool = False
    live_transport_implemented: bool = False
    operational_capability: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "observed_at": self.observed_at,
            "query": self.query,
            "status": self.status,
            "evidence_count": self.evidence_count,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "report": self.report,
            "evidence_tier": self.evidence_tier,
            "retry_attempts_allowed": self.retry_attempts_allowed,
            "commercial_eligible": False,
            "live_transport_implemented": False,
            "operational_capability": False,
            "eligible_live_source": None,
        }


def health() -> AdapterHealth:
    return AdapterHealth(
        name=SOURCE,
        configured=True,
        reachable=False,
        capabilities=("blocked_commercial_ineligible", "offline_demo_opt_in_only", "dry_run_only"),
        detail=(
            f"{SOURCE} ({REPORT_VERSION}); no eligible commercial attention source "
            f"(docs rechecked {DOC_RECHECK_DATE}; FAQ accessed {ACCESS_DATE})"
        ),
    )


def _from_report(report: TikTokResearchEvidenceReport, *, query: str) -> TikTokResearchBridgeEvidence:
    data = report.to_dict()
    return TikTokResearchBridgeEvidence(
        source=SOURCE,
        observed_at=float(data.get("observed_at") or time.time()),
        query=query,
        status=str(data.get("capability_status") or "blocked_ineligible_commercial_use"),
        evidence_count=int(data.get("evidence_count") or 0),
        blockers=tuple(str(item) for item in data.get("blockers") or ()),
        warnings=tuple(str(item) for item in data.get("warnings") or ()),
        report=data,
        operational_capability=False,
    )


def fetch_research_evidence(
    query: str,
    *,
    context: SidecarContext,
    mode: str = "blocked_ineligible_commercial_use",
    fixture_path: str | Path | None = None,
    rows: Sequence[Mapping[str, Any]] | None = None,
    transport: TikTokResearchTransport | None = None,
    allow_offline_demo: bool = False,
) -> TikTokResearchBridgeEvidence:
    """Fail-closed bridge into the TikTok commercial-attention capability contract.

    Ordinary dry-run returns blocked/unavailable with zero rows. Offline demos
    require ``allow_offline_demo=True`` and an explicit fixture/rows/transport.
    ``context.dry_run=False`` never loads fixtures and returns ``blocked_live_mode``.
    """
    cleaned = " ".join((query or "").split()) or "tiktok-research"
    if not context.dry_run:
        report = build_tiktok_research_evidence(
            mode="blocked_ineligible_commercial_use",
            allow_live=True,
            workspace_id=context.workspace_id or "offline-tiktok-research",
        )
        bridge = _from_report(report, query=cleaned)
        return TikTokResearchBridgeEvidence(
            source=bridge.source,
            observed_at=bridge.observed_at,
            query=cleaned,
            status="blocked_live_mode",
            evidence_count=0,
            blockers=bridge.blockers + ("live_mode_requested",) + _LIVE_PREREQUISITES,
            warnings=bridge.warnings + ("No eligible TikTok commercial attention live transport.",),
            report={},
            operational_capability=False,
        )

    try:
        # Never auto-load DEFAULT_FIXTURE as an operational path.
        report = build_tiktok_research_evidence(
            mode=mode,
            fixture_path=fixture_path,
            rows=rows,
            transport=transport,
            transport_request={"surface": "research_api", "query": cleaned, "dry_run": True},
            allow_live=False,
            allow_offline_demo=allow_offline_demo,
            workspace_id=context.workspace_id or "offline-tiktok-research",
        )
    except Exception:
        _log.warning("tiktok_research_offline_builder_failed mode=%s", mode)
        return TikTokResearchBridgeEvidence(
            source=SOURCE,
            observed_at=time.time(),
            query=cleaned,
            status="error",
            evidence_count=0,
            blockers=("offline_builder_failed",),
            warnings=("TikTok research offline builder failed unexpectedly; details withheld.",),
            report={},
            operational_capability=False,
        )
    return _from_report(report, query=cleaned)


def to_additional_evidence(evidence: TikTokResearchBridgeEvidence) -> dict[str, Any]:
    """Shape for ResearchCandidate.additional_evidence (supplemental only)."""
    return {
        "kind": "tiktok_research_tools_attention",
        "evidence_tier": EVIDENCE_TIER,
        "status": evidence.status,
        "evidence_count": evidence.evidence_count,
        "commercial_eligible": False,
        "live_transport_implemented": False,
        "operational_capability": False,
        "eligible_live_source": None,
        "blockers": list(evidence.blockers)[:12],
        "warnings": list(evidence.warnings)[:12],
        "authority": {
            "publish": False,
            "spend": False,
            "ad_creation": False,
            "purchase_evidence": False,
            "supplier_proof": False,
        },
    }


class TikTokResearchEvidenceAdapter:
    """Stateless wrapper; async only for ProductResearchProvider parity."""

    async def discover(self, query: str, *, context: SidecarContext) -> Sequence[Mapping[str, Any]]:
        evidence = fetch_research_evidence(
            query,
            context=context,
            mode="blocked_ineligible_commercial_use",
            allow_offline_demo=False,
        )
        return (to_additional_evidence(evidence),)


__all__ = [
    "DEFAULT_FIXTURE",
    "EVIDENCE_TIER",
    "FakeTikTokResearchTransport",
    "SOURCE",
    "TikTokResearchBridgeEvidence",
    "TikTokResearchEvidenceAdapter",
    "fetch_research_evidence",
    "health",
    "official_citations",
    "render_markdown",
    "research_tool_capabilities",
    "to_additional_evidence",
]
