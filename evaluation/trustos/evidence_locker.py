"""Metadata-only evidence locker for TrustOS controls."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .control_plane import TrustEvidenceExportPolicy, TrustEvidenceExpiry, TrustEvidenceRecord, TrustEvidenceRedaction, TrustEvidenceSource, _clean, EVIDENCE_STATUSES


@dataclass(frozen=True)
class TrustEvidenceLocker:
    records: tuple[TrustEvidenceRecord, ...]
    sources: tuple[TrustEvidenceSource, ...]
    expiries: tuple[TrustEvidenceExpiry, ...]
    redactions: tuple[TrustEvidenceRedaction, ...]
    export_policy: TrustEvidenceExportPolicy
    artifacts_stored: bool = False

    def __post_init__(self) -> None:
        if self.artifacts_stored:
            raise ValueError("TrustOS evidence locker is metadata-only")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)

    def missing(self) -> tuple[TrustEvidenceRecord, ...]:
        return tuple(item for item in self.records if item.status in {"missing", "draft", "requires_review"})

    def client_visible(self) -> tuple[TrustEvidenceRecord, ...]:
        return tuple(item for item in self.records if item.client_visible and not item.internal_only)


def build_evidence_locker(records: Iterable[TrustEvidenceRecord] = ()) -> TrustEvidenceLocker:
    records = tuple(records)
    sources = tuple(TrustEvidenceSource(f"source-{item.source_type}", item.source_type, "Metadata reference only.", "reference_only") for item in records)
    expiries = tuple(TrustEvidenceExpiry(item.evidence_id, item.expires_at, "warn", "Evidence freshness must be reviewed before gated action.") for item in records if item.expires_at != "TBD")
    redactions = tuple(TrustEvidenceRedaction(item.evidence_id, ("notes", "source_ref"), "client_safe_minimal_export", item.client_visible) for item in records)
    policy = TrustEvidenceExportPolicy("client-safe-evidence-v1", ("evidence_id", "control_id", "summary", "status", "professional_review_required"), ("raw_payload", "internal_notes", "prompt", "formula", "cross_client_data"), ("source_ref", "notes"))
    return TrustEvidenceLocker(records, sources, expiries, redactions, policy, False)


__all__ = ["TrustEvidenceLocker", "TrustEvidenceRecord", "TrustEvidenceSource", "TrustEvidenceExpiry", "TrustEvidenceRedaction", "TrustEvidenceExportPolicy", "build_evidence_locker", "EVIDENCE_STATUSES"]
