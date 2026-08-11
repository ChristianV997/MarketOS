"""JSON-safe models for Commerce Intelligence evaluation reports.

The models deliberately use metric dictionaries.  This keeps the evaluation
contract additive as an engine gains a new quality signal without creating a
second domain model for supplier, competition, opportunity, or research data.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool, float)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


@dataclass(frozen=True)
class EngineEvaluation:
    engine: str
    status: str
    sample_size: int
    metrics: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["metrics"] = _json_safe(self.metrics)
        value["warnings"] = list(self.warnings)
        return value


@dataclass(frozen=True)
class ReproducibilityReport:
    event_count: int
    unique_event_ids: int
    duplicate_event_ids: int
    replay_hash_count: int
    replay_hash_digest: str
    replay_hash_available: bool
    stable_event_order: bool
    reproducible: bool
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["warnings"] = list(self.warnings)
        return value


@dataclass(frozen=True)
class ComparisonReport:
    baseline_run_id: str
    current_run_id: str
    deltas: dict[str, float | None] = field(default_factory=dict)
    improved_metrics: tuple[str, ...] = ()
    worsened_metrics: tuple[str, ...] = ()
    unchanged_metrics: tuple[str, ...] = ()
    ranking_stability: float | None = None
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["deltas"] = _json_safe(self.deltas)
        value["improved_metrics"] = list(self.improved_metrics)
        value["worsened_metrics"] = list(self.worsened_metrics)
        value["unchanged_metrics"] = list(self.unchanged_metrics)
        value["notes"] = list(self.notes)
        return value


@dataclass(frozen=True)
class EvaluationReport:
    framework_version: str
    report_id: str
    workspace_id: str | None
    run_id: str
    input_kind: str
    source_fingerprint: str
    event_count: int
    engines: tuple[EngineEvaluation, ...]
    overall: dict[str, Any]
    reproducibility: ReproducibilityReport
    comparison: ComparisonReport | None = None
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    read_only: bool = True
    mutated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "framework_version": self.framework_version,
            "report_id": self.report_id,
            "workspace_id": self.workspace_id,
            "run_id": self.run_id,
            "input_kind": self.input_kind,
            "source_fingerprint": self.source_fingerprint,
            "event_count": self.event_count,
            "engines": {item.engine: item.to_dict() for item in self.engines},
            "overall": _json_safe(self.overall),
            "reproducibility": self.reproducibility.to_dict(),
            "comparison": self.comparison.to_dict() if self.comparison else None,
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
            "read_only": self.read_only,
            "mutated": self.mutated,
        }


__all__ = ["ComparisonReport", "EngineEvaluation", "EvaluationReport", "ReproducibilityReport"]
