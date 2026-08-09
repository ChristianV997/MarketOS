"""JSON-safe domain records for read-only shadow feature evaluation."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


PROMOTE = "PROMOTE"
KEEP_SHADOW = "KEEP_SHADOW"
REWORK = "REWORK"
DELETE = "DELETE"
CLASSIFICATIONS = {PROMOTE, KEEP_SHADOW, REWORK, DELETE}


def _safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


@dataclass(frozen=True)
class EvaluationMetric:
    name: str
    value: float
    baseline_value: float
    candidate_value: float
    delta: float
    direction: str = "higher_is_better"
    tolerance: float = 0.0
    passed: bool = False
    weight: float = 1.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _safe(asdict(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvaluationMetric":
        return cls(**data)


@dataclass(frozen=True)
class SafetyMetric:
    name: str
    baseline_value: float
    candidate_value: float
    max_tolerated_regression: float
    passed: bool
    blocker: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _safe(asdict(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SafetyMetric":
        return cls(**data)


@dataclass(frozen=True)
class EvidenceRequirement:
    minimum_sample_size: int
    required_event_types: list[str]
    required_metric_names: list[str]
    required_workspace_coverage: int = 1
    requires_no_live_authority: bool = True
    requires_no_safety_blockers: bool = True
    requires_correlation_chain: bool = True
    requires_financial_projection: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _safe(asdict(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceRequirement":
        return cls(**data)


@dataclass(frozen=True)
class ShadowFeatureEvaluation:
    feature_id: str
    classification: str
    fixture_name: str
    sample_size: int
    confidence_level: str
    primary_metrics: list[EvaluationMetric]
    safety_metrics: list[SafetyMetric]
    blockers: list[str]
    warnings: list[str]
    evidence_event_ids: list[str]
    replay_hashes: list[str]
    recommendation: str
    rationale: list[str]
    requirement: EvidenceRequirement

    def __post_init__(self) -> None:
        if self.classification not in CLASSIFICATIONS:
            raise ValueError(f"unsupported classification: {self.classification}")

    def to_dict(self) -> dict[str, Any]:
        return _safe(asdict(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ShadowFeatureEvaluation":
        copy = dict(data)
        copy["primary_metrics"] = [EvaluationMetric.from_dict(item) for item in copy.get("primary_metrics", [])]
        copy["safety_metrics"] = [SafetyMetric.from_dict(item) for item in copy.get("safety_metrics", [])]
        copy["requirement"] = EvidenceRequirement.from_dict(copy["requirement"])
        return cls(**copy)


@dataclass(frozen=True)
class EvaluationReport:
    report_id: str
    generated_at: float
    fixtures_evaluated: list[str]
    features: list[ShadowFeatureEvaluation]
    summary_counts: dict[str, int]
    global_blockers: list[str]
    migration_readiness: dict[str, Any]
    recommended_next_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return _safe(asdict(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvaluationReport":
        copy = dict(data)
        copy["features"] = [ShadowFeatureEvaluation.from_dict(item) for item in copy.get("features", [])]
        return cls(**copy)
