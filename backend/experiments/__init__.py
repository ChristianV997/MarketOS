"""backend.experiments — CommercialRunEnvelope and its audit trail.

Public surface:
    CommercialRunEnvelope   — durable per-run record (subclasses BaseArtifact)
    ExperimentRegistry      — thin view over the existing ArtifactRegistry
    get_experiment_registry — singleton accessor
    log_transition          — append a status-change event (event_store-backed)
    transitions_for         — read back an envelope's logged events
"""
from .audit_log import log_transition, transitions_for
from .envelope import ARTIFACT_TYPE, STATUSES, CommercialRunEnvelope
from .registry import ExperimentRegistry, get_experiment_registry

__all__ = [
    "CommercialRunEnvelope",
    "ARTIFACT_TYPE",
    "STATUSES",
    "ExperimentRegistry",
    "get_experiment_registry",
    "log_transition",
    "transitions_for",
]
