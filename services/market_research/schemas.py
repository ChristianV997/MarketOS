"""services.market_research.schemas — typed request/result contracts for
the product-agnostic Market Research service.

This service never scores, ranks, or grants launch authority itself. It
composes evidence reports the caller already built from the existing
marketplace-trends, public-market-benchmark, supplier-feasibility, and
consumer-attention authorities (evaluation.commerce.*), fuses them via the
one existing fusion authority
(evaluation.commerce.opportunity_synthesis.build_product_opportunity_synthesis),
and re-presents the result as a consulting-ready report. Every evidence
field is optional; an omitted pillar is reported as missing, never
defaulted to a positive, zero, or "clear" result.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Mapping

OFFERING_KINDS = ("goods", "service", "hybrid", "unknown")
DEFAULT_OFFERING_KIND = "unknown"

# Evidence classes an evidence-matrix row can carry. "conflict" means two
# supplied sources disagree (surfaced by opportunity_synthesis's own alias
# collision detection); "stale"/"future" are read from the caller-supplied
# report's own observed_at/as_of-shaped fields, never computed by comparing
# against a live clock this service does not have.
EVIDENCE_STATUSES = ("supplied", "missing", "stale", "future", "conflict")

FIXTURE_LIKE_EVIDENCE_MODES = frozenset({"fixture", "fixture_demo", "manual_import", "manual"})
LIVE_EVIDENCE_MODES = frozenset({"observed", "live_readonly", "verified", "sanitized_report"})


@dataclass(frozen=True)
class MarketResearchRequest:
    """Bounded, offline input to build_market_research_report.

    ``*_report`` fields are the exact dict shapes the corresponding
    existing authority already produces
    (evaluation.commerce.marketplace_trends.build_report,
    evaluation.commerce.public_market_benchmark.build_public_market_benchmark,
    evaluation.commerce.supplier_feasibility's report,
    evaluation.commerce.consumer_attention.build_report,
    evaluation.commerce.product_validation_report.generate). This service
    never fetches, mocks, or re-derives any of them -- an omitted field is
    reported as missing.
    """
    candidate_id: str
    offering_kind: str = DEFAULT_OFFERING_KIND
    geography: str = ""
    language: str = ""
    as_of: str = ""
    marketplace_report: Mapping[str, Any] | None = None
    supplier_report: Mapping[str, Any] | None = None
    consumer_report: Mapping[str, Any] | None = None
    product_validation_report: Mapping[str, Any] | None = None
    public_market_benchmark_report: Mapping[str, Any] | None = None
    client_context: Mapping[str, Any] | None = None
    workspace_id: str = ""


@dataclass(frozen=True)
class EvidenceMatrixRow:
    pillar: str
    status: str
    evidence_mode: str | None
    observed_at: str | None
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "pillar": self.pillar,
            "status": self.status,
            "evidence_mode": self.evidence_mode,
            "observed_at": self.observed_at,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class ValidationStep:
    window: str
    task: str
    owner: str = "operator"

    def to_dict(self) -> dict[str, Any]:
        return {"window": self.window, "task": self.task, "owner": self.owner}


@dataclass
class MarketResearchResult:
    report_version: str
    candidate_id: str
    workspace_id: str
    candidate_title: str
    offering_kind: str
    offering_kind_recognized: bool
    geography: str
    language: str
    executive_summary: dict[str, Any]
    evidence_matrix: tuple[EvidenceMatrixRow, ...]
    demand_and_customer_evidence: dict[str, Any]
    competitor_and_substitute_evidence: dict[str, Any]
    marketplace_and_public_signals: dict[str, Any]
    supplier_feasibility: dict[str, Any]
    delivery_and_logistics_feasibility: dict[str, Any]
    pricing_and_willingness_to_pay: dict[str, Any]
    assumptions: tuple[str, ...]
    observed_facts: tuple[str, ...]
    source_conflicts: tuple[str, ...]
    confidence_grade: str
    limitations: tuple[str, ...]
    blockers: tuple[str, ...]
    risks: tuple[str, ...]
    next_action: str
    validation_plan: tuple[ValidationStep, ...]
    follow_up_modules: tuple[str, ...]
    fingerprint: str
    source_reports: dict[str, str]
    observation_source_identity: tuple[dict[str, Any], ...]
    freshness: tuple[dict[str, Any], ...]
    conflict_findings: tuple[dict[str, Any], ...]
    evidence_class: str
    source_provenance: tuple[dict[str, Any], ...]
    missing_data: tuple[str, ...]
    client_safe_export_status: str
    client_safe_projection: dict[str, Any]
    next_research_actions: tuple[str, ...]
    evidence_integrity_fingerprint: str
    dry_run: bool = True
    read_only: bool = True
    network_calls: bool = False
    mutated: bool = False
    status: str = "ready_for_client_service"
    generated_at: float = field(default_factory=time.time)
    disclaimer: str = (
        "This report is offline validation guidance composed from the evidence supplied. "
        "It is not legal, tax, customs, supplier, or launch authorization, and it never "
        "certifies a product or service as compliant, validated, or ready to launch."
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_version": self.report_version,
            "candidate_id": self.candidate_id,
            "workspace_id": self.workspace_id,
            "candidate_title": self.candidate_title,
            "offering_kind": self.offering_kind,
            "offering_kind_recognized": self.offering_kind_recognized,
            "geography": self.geography,
            "language": self.language,
            "executive_summary": self.executive_summary,
            "evidence_matrix": [row.to_dict() for row in self.evidence_matrix],
            "demand_and_customer_evidence": self.demand_and_customer_evidence,
            "competitor_and_substitute_evidence": self.competitor_and_substitute_evidence,
            "marketplace_and_public_signals": self.marketplace_and_public_signals,
            "supplier_feasibility": self.supplier_feasibility,
            "delivery_and_logistics_feasibility": self.delivery_and_logistics_feasibility,
            "pricing_and_willingness_to_pay": self.pricing_and_willingness_to_pay,
            "assumptions": list(self.assumptions),
            "observed_facts": list(self.observed_facts),
            "source_conflicts": list(self.source_conflicts),
            "confidence_grade": self.confidence_grade,
            "limitations": list(self.limitations),
            "blockers": list(self.blockers),
            "risks": list(self.risks),
            "next_action": self.next_action,
            "validation_plan": [step.to_dict() for step in self.validation_plan],
            "follow_up_modules": list(self.follow_up_modules),
            "fingerprint": self.fingerprint,
            "source_reports": dict(self.source_reports),
            "observation_source_identity": [dict(item) for item in self.observation_source_identity],
            "freshness": [dict(item) for item in self.freshness],
            "conflict_findings": [dict(item) for item in self.conflict_findings],
            "evidence_class": self.evidence_class,
            "source_provenance": [dict(item) for item in self.source_provenance],
            "missing_data": list(self.missing_data),
            "client_safe_export_status": self.client_safe_export_status,
            "client_safe_projection": dict(self.client_safe_projection),
            "next_research_actions": list(self.next_research_actions),
            "evidence_integrity_fingerprint": self.evidence_integrity_fingerprint,
            "dry_run": self.dry_run,
            "read_only": self.read_only,
            "network_calls": self.network_calls,
            "mutated": self.mutated,
            "status": self.status,
            "generated_at": self.generated_at,
            "disclaimer": self.disclaimer,
        }


__all__ = [
    "OFFERING_KINDS",
    "DEFAULT_OFFERING_KIND",
    "EVIDENCE_STATUSES",
    "FIXTURE_LIKE_EVIDENCE_MODES",
    "LIVE_EVIDENCE_MODES",
    "MarketResearchRequest",
    "EvidenceMatrixRow",
    "ValidationStep",
    "MarketResearchResult",
]
