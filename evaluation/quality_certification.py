"""evaluation.quality_certification — Thin backward-compatibility adapter for evaluation.quality.

CANONICAL AUTHORITY: evaluation.quality
All quality assertion states, expectation rules, exception types, and deterministic
replay certification logic have been consolidated into evaluation.quality as the
canonical data-quality authority for MarketOS. This module remains as an adapter
to maintain backward compatibility for existing callers without creating authority
duplication.
"""
from __future__ import annotations

from evaluation.quality import (
    CANONICAL_QUALITY_AUTHORITY,
    REJECTED_ORCHESTRATORS,
    AssertionIntegrityError,
    DeterministicReplayCertifier,
    DuplicateAuthorityError,
    DuplicateOrchestratorError,
    ExpectationRule,
    ExpectationSuite,
    InvalidEvidencePromotionError,
    QualityAssertionResult,
    QualityAssertionState,
    ReplayCertificationReport,
    SecretLeakError,
    StaleEvidenceError,
    UnredactedPayloadError,
    certify_data_quality,
    deduplicate_observations,
    quality_reasons,
    quality_state_to_local_gate_class,
    quality_state_to_trustos_evidence_status,
    trustos_evidence_status_to_quality_state,
)

__all__ = [
    "QualityAssertionState",
    "QualityAssertionResult",
    "ExpectationRule",
    "ExpectationSuite",
    "ReplayCertificationReport",
    "DeterministicReplayCertifier",
    "InvalidEvidencePromotionError",
    "StaleEvidenceError",
    "AssertionIntegrityError",
    "UnredactedPayloadError",
    "SecretLeakError",
    "DuplicateOrchestratorError",
    "DuplicateAuthorityError",
    "CANONICAL_QUALITY_AUTHORITY",
    "REJECTED_ORCHESTRATORS",
    "quality_reasons",
    "deduplicate_observations",
    "certify_data_quality",
    "quality_state_to_trustos_evidence_status",
    "trustos_evidence_status_to_quality_state",
    "quality_state_to_local_gate_class",
]
