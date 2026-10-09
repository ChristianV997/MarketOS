from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .evidence_source_contract import EvidenceRecord

# Internal filesystem paths stay on the in-memory job for local processing only.
# Client-facing / persisted projections must omit them so TrustOS leakage checks
# (evaluation.trustos.client_workspace_isolation) do not see path-shaped values.
_CLIENT_OMITTED_JOB_FIELDS = frozenset({"input_path"})


@dataclass
class EvidenceImportJob:
    import_id: str
    workspace_id: str
    source_name: str
    source_type: str
    input_path: str
    parser_type: str
    status: str = "created"
    records_imported: int = 0
    records_rejected: int = 0
    warnings: list[str] = field(default_factory=list)
    blocked_reasons: list[str] = field(default_factory=list)
    created_at: float = 0.0
    finished_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            key: getattr(self, key)
            for key in self.__dataclass_fields__
            if key not in _CLIENT_OMITTED_JOB_FIELDS
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceImportJob":
        payload = {key: data[key] for key in cls.__dataclass_fields__ if key in data}
        # Client-safe / registry projections omit input_path; default empty for reload.
        if "input_path" not in payload:
            payload["input_path"] = ""
        return cls(**payload)


@dataclass
class EvidenceSourceQuality:
    source_name: str
    source_type: str
    quality_score: float
    confidence_multiplier: float
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    allowed_signal_types: list[str] = field(default_factory=list)
    blocked_signal_types: list[str] = field(default_factory=list)
    freshness_label: str = "static"
    provenance_requirements: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.quality_score = max(0.0, min(float(self.quality_score), 100.0))
        self.confidence_multiplier = max(0.0, min(float(self.confidence_multiplier), 1.0))

    def to_dict(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceSourceQuality":
        return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})


@dataclass
class EvidenceNormalizationResult:
    records: list[EvidenceRecord]
    rejected: list[dict[str, Any]]
    warnings: list[str]
    source_quality: EvidenceSourceQuality
    import_job: EvidenceImportJob

    def to_dict(self) -> dict[str, Any]:
        return {
            "records": [record.to_dict() for record in self.records],
            "rejected": self.rejected,
            "warnings": self.warnings,
            "source_quality": self.source_quality.to_dict(),
            "import_job": self.import_job.to_dict(),
        }
