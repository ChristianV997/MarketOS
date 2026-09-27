"""Product-agnostic, offline opportunity discovery contracts."""

from .service import (
    DISCOVERY_MODES,
    EVIDENCE_CLASSES,
    EVIDENCE_STATUSES,
    OpportunityCandidate,
    OpportunityDecision,
    OpportunityDiscoveryError,
    OpportunityEvidence,
    DiscoveryRun,
    ValidationExperiment,
    load_payload,
    render_markdown,
    run_discovery,
)

__all__ = [
    "DISCOVERY_MODES",
    "EVIDENCE_CLASSES",
    "EVIDENCE_STATUSES",
    "DiscoveryRun",
    "OpportunityCandidate",
    "OpportunityDecision",
    "OpportunityDiscoveryError",
    "OpportunityEvidence",
    "ValidationExperiment",
    "load_payload",
    "render_markdown",
    "run_discovery",
]
