"""backend.observability.lineage_facets — Run-level evidence lineage and asset facets.

Adapted from OpenLineage (v1.28.0, Apache-2.0) and Dagster (1.9.10, Apache-2.0) patterns.
Provides lightweight, typed, deterministic provenance facets for MarketOS evidence
without introducing external daemon, heavy SDK, or secondary orchestrator dependencies.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence

_SECRET_SHAPED_VALUE = re.compile(
    r"(?is)("
    r"-----begin (?:rsa |ec |dsa |openssh )?private key-----"
    r"|ghp_[A-Za-z0-9_]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|sk-(?:live|test)?-?[A-Za-z0-9]{16,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|bearer [A-Za-z0-9._-]{10,}"
    r")"
)

_FORBIDDEN_RAW_KEYS = frozenset({
    "raw_html", "raw_payload", "raw_body", "raw_response",
    "unredacted_html", "raw_dump", "full_page_html", "cookie_header"
})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_dict(data: Mapping[str, Any]) -> str:
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class LineageSecurityError(ValueError):
    """Raised when lineage metadata violates security or privacy invariants."""


@dataclass(frozen=True)
class RunFacet:
    """Emulates OpenLineage RunFacet.

    Represents a specific execution step or transformation job run.
    """
    run_id: str
    job_name: str
    nominal_start_time: str = field(default_factory=_now_iso)
    nominal_end_time: Optional[str] = None
    code_version: str = "df59a0609897907c1565d7d5f78e20959095d430"
    environment: str = "offline_fixture"
    parent_run_id: Optional[str] = None
    orchestrator: str = "marketos_event_spine"

    def __post_init__(self) -> None:
        if self.orchestrator != "marketos_event_spine":
            raise LineageSecurityError(
                f"Invalid orchestrator '{self.orchestrator}': MarketOS requires the singular marketos_event_spine"
            )
        if self.environment == "live_unmetered":
            raise LineageSecurityError("Unmetered live execution is prohibited in lineage facets")


@dataclass(frozen=True)
class DatasetFacet:
    """Emulates OpenLineage DatasetFacet.

    Represents an input or output dataset snapshot consumed or produced by a run.
    """
    namespace: str
    dataset_name: str
    version_hash: str
    schema_fingerprint: tuple[str, ...]
    lifecycle_stage: str = "static_fixture"  # static_fixture, simulated, live_attributed

    def __post_init__(self) -> None:
        valid_stages = {"static_fixture", "synthetic", "simulated", "live_attributed", "dry_run"}
        if self.lifecycle_stage not in valid_stages:
            raise LineageSecurityError(f"Invalid lifecycle stage: '{self.lifecycle_stage}'")


@dataclass(frozen=True)
class AssetFacet:
    """Emulates Dagster Software-Defined Asset (SDA) Lineage metadata.

    Allows tracking evidence items as declaratively versioned data assets.
    """
    asset_key: str
    partition_key: str = ""
    materialization_version: str = "v1.0.0"
    upstream_asset_keys: tuple[str, ...] = ()
    tags: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class EvidenceLineageFacet:
    """Consolidated lineage facet container attached to MarketOS evidence records."""
    lineage_id: str
    run: RunFacet
    inputs: tuple[DatasetFacet, ...]
    output: DatasetFacet
    asset: Optional[AssetFacet] = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Serialize lineage facet cleanly to standard dictionary."""
        d: dict[str, Any] = {
            "lineage_id": self.lineage_id,
            "run": asdict(self.run),
            "inputs": [asdict(inp) for inp in self.inputs],
            "output": asdict(self.output),
            "created_at": self.created_at,
        }
        if self.asset:
            d["asset"] = {
                "asset_key": self.asset.asset_key,
                "partition_key": self.asset.partition_key,
                "materialization_version": self.asset.materialization_version,
                "upstream_asset_keys": list(self.asset.upstream_asset_keys),
                "tags": dict(self.asset.tags),
            }
        return d

    def fingerprint(self) -> str:
        """Compute deterministic SHA256 fingerprint of the entire lineage graph."""
        return _hash_dict(self.to_dict())

    def validate_safety(self) -> None:
        """Enforce strict security boundaries on the lineage graph."""
        lineage_dict = self.to_dict()
        serialized = json.dumps(lineage_dict, default=str)

        # 1. Check for raw payloads
        for key in _FORBIDDEN_RAW_KEYS:
            if f'"{key}"' in serialized:
                raise LineageSecurityError(f"Forbidden raw payload key '{key}' detected in lineage metadata")

        # 2. Check for credential-shaped patterns
        if _SECRET_SHAPED_VALUE.search(serialized):
            raise LineageSecurityError("Secret-shaped credential pattern detected in lineage metadata")

        # 3. Check for orchestrator injection
        if self.run.orchestrator != "marketos_event_spine":
            raise LineageSecurityError("External orchestrator injection rejected")


def create_evidence_lineage(
    run_id: str,
    job_name: str,
    input_datasets: Sequence[DatasetFacet],
    output_dataset: DatasetFacet,
    *,
    asset_key: Optional[str] = None,
    upstream_asset_keys: Sequence[str] = (),
    environment: str = "offline_fixture",
    code_version: str = "df59a0609897907c1565d7d5f78e20959095d430",
    parent_run_id: Optional[str] = None,
    asset_tags: Optional[Mapping[str, str]] = None,
) -> EvidenceLineageFacet:
    """Factory helper to create a validated EvidenceLineageFacet."""
    run_facet = RunFacet(
        run_id=run_id,
        job_name=job_name,
        code_version=code_version,
        environment=environment,
        parent_run_id=parent_run_id,
        orchestrator="marketos_event_spine",
    )

    asset_facet: Optional[AssetFacet] = None
    if asset_key or asset_tags:
        tags_tuple = tuple(sorted(asset_tags.items())) if asset_tags else ()
        asset_facet = AssetFacet(
            asset_key=asset_key or "default_asset",
            materialization_version="v1.0.0",
            upstream_asset_keys=tuple(upstream_asset_keys),
            tags=tags_tuple,
        )

    lineage_id = hashlib.sha256(f"{run_id}:{output_dataset.namespace}:{output_dataset.dataset_name}".encode("utf-8")).hexdigest()[:16]

    facet = EvidenceLineageFacet(
        lineage_id=lineage_id,
        run=run_facet,
        inputs=tuple(input_datasets),
        output=output_dataset,
        asset=asset_facet,
    )
    facet.validate_safety()
    return facet


def attach_lineage_to_evidence(evidence_record: dict[str, Any], lineage: EvidenceLineageFacet) -> dict[str, Any]:
    """Attach lineage metadata to an existing evidence dictionary in place or as copy."""
    lineage.validate_safety()
    out = dict(evidence_record)
    out["lineage"] = lineage.to_dict()
    out["lineage_fingerprint"] = lineage.fingerprint()
    return out


def create_trust_evidence_with_lineage(
    lineage: EvidenceLineageFacet,
    control_id: str,
    summary: str,
    *,
    source_type: str = "lineage_verified_pipeline",
    professional_review_required: bool = False,
    internal_only: bool = True,
) -> Any:
    """Wire lineage facet into canonical TrustOS TrustEvidenceRecord.

    Reuses existing TrustOS evidence locker and control plane contracts rather than
    creating a second evidence system or second promotion gate.
    """
    lineage.validate_safety()
    from evaluation.trustos.control_plane import TrustEvidenceRecord

    return TrustEvidenceRecord(
        evidence_id=f"evidence-lineage-{lineage.lineage_id}",
        control_id=control_id,
        source_type=source_type,
        source_ref=f"trustos://lineage/{lineage.lineage_id}?fp={lineage.fingerprint()[:16]}",
        summary=summary,
        owner_department="operations",
        created_at=lineage.run.nominal_start_time,
        expires_at="TBD",
        status="passed",
        redaction_status="client_safe_minimal_export",
        client_visible=not internal_only,
        internal_only=internal_only,
        professional_review_required=professional_review_required,
        notes=f"Lineage verified job={lineage.run.job_name} orchestrator={lineage.run.orchestrator} inputs={len(lineage.inputs)}",
    )


def attach_lineage_to_data_quality(quality: Any, lineage: EvidenceLineageFacet) -> Any:
    """Wire lineage facet into existing DataQuality contract record."""
    lineage.validate_safety()
    from evaluation.contracts import DataQuality

    if not isinstance(quality, DataQuality):
        raise TypeError(f"Expected evaluation.contracts.DataQuality, got {type(quality)}")

    ref = f"lineage://{lineage.lineage_id}?fp={lineage.fingerprint()[:16]}"
    return DataQuality(
        provenance=quality.provenance,
        attribution=quality.attribution,
        completeness=quality.completeness,
        observed_at=quality.observed_at,
        source_ref=ref,
    )


def format_lineage_for_report(lineage: EvidenceLineageFacet) -> dict[str, Any]:
    """Provide a client-safe sanitized summary of lineage facets for report projections."""
    lineage.validate_safety()
    return {
        "lineage_id": lineage.lineage_id,
        "job_name": lineage.run.job_name,
        "orchestrator": lineage.run.orchestrator,
        "fingerprint": lineage.fingerprint(),
        "input_dataset_count": len(lineage.inputs),
        "output_dataset": f"{lineage.output.namespace}.{lineage.output.dataset_name}",
        "lifecycle_stage": lineage.output.lifecycle_stage,
        "has_asset_metadata": lineage.asset is not None,
    }


__all__ = [
    "RunFacet",
    "DatasetFacet",
    "AssetFacet",
    "EvidenceLineageFacet",
    "LineageSecurityError",
    "create_evidence_lineage",
    "attach_lineage_to_evidence",
    "create_trust_evidence_with_lineage",
    "attach_lineage_to_data_quality",
    "format_lineage_for_report",
]
