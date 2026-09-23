"""services.market_research_evidence — evidence provenance, freshness, and
deterministic conflict contract for market-research evidence.

Disjoint from `services.market_research` (productization vertical, PR #307):
this package adds no scorer, ranker, economics kernel, provider, or gate. It
composes `evaluation.commerce.opportunity_synthesis` (existing fusion
authority, reused as-is for its alias-collapse notes) and
`evaluation.trustos.client_workspace_isolation.check_workspace_leakage`
(existing TrustOS client-safety boundary, reused as-is).
"""
from __future__ import annotations

from .conflict import detect_field_conflicts
from .freshness import classify_freshness
from .identity import InvalidBindingError, build_observation_identity, build_source_identity, validate_binding, validate_candidate_id, validate_workspace_id
from .report import REPORT_VERSION, TITLE, build_evidence_integrity_report, render_evidence_integrity_markdown
from .schemas import (
    DEFAULT_FRESHNESS_DAYS,
    FRESHNESS_STATUSES,
    MISSING,
    PILLARS,
    UNKNOWN,
    ConflictFinding,
    EvidenceIntegrityResult,
    EvidenceProvenance,
    FieldObservation,
    NegativeControls,
    ObservationIdentity,
    SourceIdentity,
)

__all__ = [
    "REPORT_VERSION",
    "TITLE",
    "build_evidence_integrity_report",
    "render_evidence_integrity_markdown",
    "detect_field_conflicts",
    "classify_freshness",
    "validate_binding",
    "validate_candidate_id",
    "validate_workspace_id",
    "build_source_identity",
    "build_observation_identity",
    "InvalidBindingError",
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
