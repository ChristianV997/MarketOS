"""services.market_research_evidence.schemas — typed evidence-provenance,
freshness, and conflict contracts for market-research evidence.

This module defines data only. It creates no scorer, ranker, economics
kernel, provider, or gate: candidate ranking and recommendation remain the
sole responsibility of `evaluation.commerce.opportunity_synthesis`.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

MISSING = "missing"
UNKNOWN = "unknown"

FRESHNESS_STATUSES = ("supplied", "stale", "future", "unknown", "missing")
DEFAULT_FRESHNESS_DAYS = 180

PILLARS = (
    "marketplace",
    "supplier",
    "consumer_attention",
    "public_market_benchmark",
    "product_validation",
)


@dataclass(frozen=True)
class SourceIdentity:
    """Who produced one observation: a pillar plus its own reference,
    never a live provider connection."""

    source_family: str
    source_ref: str
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {"source_family": self.source_family, "source_ref": self.source_ref, "fingerprint": self.fingerprint}


@dataclass(frozen=True)
class ObservationIdentity:
    """What fact is being observed: one candidate, one workspace, one
    field — the join key conflict detection groups on."""

    candidate_id: str
    workspace_id: str
    field: str
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {"candidate_id": self.candidate_id, "workspace_id": self.workspace_id, "field": self.field, "fingerprint": self.fingerprint}


@dataclass(frozen=True)
class EvidenceProvenance:
    pillar: str
    source: SourceIdentity
    observation: ObservationIdentity
    evidence_mode: str
    observed_at: str
    freshness_status: str
    capture_method: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "pillar": self.pillar,
            "source": self.source.to_dict(),
            "observation": self.observation.to_dict(),
            "evidence_mode": self.evidence_mode,
            "observed_at": self.observed_at,
            "freshness_status": self.freshness_status,
            "capture_method": self.capture_method,
        }


@dataclass(frozen=True)
class FieldObservation:
    """One pillar's reported value for one candidate/field, with the
    missing-vs-zero distinction preserved: `value` is the literal string
    'missing' when the field was never supplied, never a coerced 0."""

    field: str
    value: Any
    provenance: EvidenceProvenance

    def to_dict(self) -> dict[str, Any]:
        return {"field": self.field, "value": self.value, "provenance": self.provenance.to_dict()}


@dataclass(frozen=True)
class ConflictFinding:
    """A deterministic, field-level disagreement between two or more
    independently sourced observations of the same candidate/field —
    computed directly from the supplied numeric values, not inferred
    from `opportunity_synthesis`'s alias-collapse notes."""

    candidate_id: str
    field: str
    observations: tuple[dict[str, Any], ...]
    delta: float
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "field": self.field,
            "observations": list(self.observations),
            "delta": self.delta,
            "note": self.note,
        }


@dataclass(frozen=True)
class NegativeControls:
    """Explicit, always-true assurances this report can never flip to
    False by construction — enforced by tests scanning both JSON and
    Markdown output for the language these guard against."""

    evidence_is_not_supplier_proof: bool = True
    evidence_is_not_legal_clearance: bool = True
    evidence_is_not_promotion_approval: bool = True
    evidence_is_not_a_launch_approval: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_is_not_supplier_proof": self.evidence_is_not_supplier_proof,
            "evidence_is_not_legal_clearance": self.evidence_is_not_legal_clearance,
            "evidence_is_not_promotion_approval": self.evidence_is_not_promotion_approval,
            "evidence_is_not_a_launch_approval": self.evidence_is_not_a_launch_approval,
        }


@dataclass
class EvidenceIntegrityResult:
    report_version: str
    candidate_id: str
    workspace_id: str
    as_of: str
    provenance_records: tuple[EvidenceProvenance, ...]
    field_observations: tuple[FieldObservation, ...]
    missing_fields: tuple[str, ...]
    unknown_freshness_fields: tuple[str, ...]
    deterministic_conflicts: tuple[ConflictFinding, ...]
    alias_collapse_notes: tuple[str, ...]
    deterministic_conflict_detected: bool
    leakage_findings: tuple[dict[str, Any], ...]
    client_export_safe: bool
    negative_controls: NegativeControls
    limitations: tuple[str, ...]
    fingerprint: str
    dry_run: bool = True
    read_only: bool = True
    network_calls: bool = False
    mutated: bool = False
    status: str = "evidence_integrity_audit_only"
    generated_at: float = field(default_factory=time.time)
    disclaimer: str = (
        "This evidence-integrity report audits provenance, freshness, and "
        "cross-source conflicts only. It is not supplier proof, legal "
        "clearance, promotion approval, or launch authorization, and it "
        "grants no ranking, scoring, or economics decision of its own."
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_version": self.report_version,
            "candidate_id": self.candidate_id,
            "workspace_id": self.workspace_id,
            "as_of": self.as_of,
            "provenance_records": [item.to_dict() for item in self.provenance_records],
            "field_observations": [item.to_dict() for item in self.field_observations],
            "missing_fields": list(self.missing_fields),
            "unknown_freshness_fields": list(self.unknown_freshness_fields),
            "deterministic_conflicts": [item.to_dict() for item in self.deterministic_conflicts],
            "alias_collapse_notes": list(self.alias_collapse_notes),
            "deterministic_conflict_detected": self.deterministic_conflict_detected,
            "leakage_findings": list(self.leakage_findings),
            "client_export_safe": self.client_export_safe,
            "negative_controls": self.negative_controls.to_dict(),
            "limitations": list(self.limitations),
            "fingerprint": self.fingerprint,
            "dry_run": self.dry_run,
            "read_only": self.read_only,
            "network_calls": self.network_calls,
            "mutated": self.mutated,
            "status": self.status,
            "generated_at": self.generated_at,
            "disclaimer": self.disclaimer,
        }


__all__ = [
    "MISSING",
    "UNKNOWN",
    "FRESHNESS_STATUSES",
    "DEFAULT_FRESHNESS_DAYS",
    "PILLARS",
    "SourceIdentity",
    "ObservationIdentity",
    "EvidenceProvenance",
    "FieldObservation",
    "ConflictFinding",
    "NegativeControls",
    "EvidenceIntegrityResult",
]
