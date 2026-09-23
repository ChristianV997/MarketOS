"""services.market_research_evidence.identity — candidate/workspace binding
plus deterministic source and observation identity.

No network calls, no registry lookups: identity here is a pure function of
the strings the caller supplies, so it is safe to call from any offline
report builder.
"""
from __future__ import annotations

import hashlib
import re

from .schemas import ObservationIdentity, SourceIdentity

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class InvalidBindingError(ValueError):
    """Raised when a candidate_id or workspace_id fails the safe-identity
    format check, so a report can never be bound to an unbounded or
    injectable identity string."""


def validate_candidate_id(candidate_id: str) -> None:
    if not isinstance(candidate_id, str) or not _SAFE_ID.fullmatch(candidate_id):
        raise InvalidBindingError("invalid candidate_id")


def validate_workspace_id(workspace_id: str) -> None:
    if not isinstance(workspace_id, str) or not _SAFE_ID.fullmatch(workspace_id):
        raise InvalidBindingError("invalid workspace_id")


def validate_binding(candidate_id: str, workspace_id: str) -> None:
    validate_candidate_id(candidate_id)
    validate_workspace_id(workspace_id)


def _fingerprint(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def build_source_identity(source_family: str, source_ref: str) -> SourceIdentity:
    source_family = str(source_family or "unknown_source_family")
    source_ref = str(source_ref or "unknown_source_ref")
    return SourceIdentity(source_family, source_ref, _fingerprint("source", source_family, source_ref))


def build_observation_identity(candidate_id: str, workspace_id: str, field: str) -> ObservationIdentity:
    validate_binding(candidate_id, workspace_id)
    field = str(field)
    return ObservationIdentity(candidate_id, workspace_id, field, _fingerprint("observation", candidate_id, workspace_id, field))


__all__ = ["InvalidBindingError", "validate_candidate_id", "validate_workspace_id", "validate_binding", "build_source_identity", "build_observation_identity"]
