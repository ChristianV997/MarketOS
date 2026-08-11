"""Evaluation service and canonical evaluation-event mapping."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from backend.contracts.events import Event
from backend.events.query_service import load_events_from_jsonl

from .metrics import (
    competition_metrics,
    margin_metrics,
    opportunity_metrics,
    overall_metrics,
    research_metrics,
    source_fingerprint,
    supplier_metrics,
)
from .models import ComparisonReport, EngineEvaluation, EvaluationReport, ReproducibilityReport

FRAMEWORK_VERSION = "commerce-evaluation-v1"
ENGINE_ORDER = (
    "supplier_evidence",
    "competition_intelligence",
    "opportunity_scoring",
    "research_portfolio",
    "margin_intelligence",
)


@dataclass(frozen=True)
class EvaluationInput:
    source: str
    path: str
    artifact: dict[str, Any]
    events: tuple[Event, ...]
    warnings: tuple[str, ...] = ()

    def event_dicts(self) -> list[dict[str, Any]]:
        return [event.to_dict() for event in self.events]


def _read_json(path: Path) -> tuple[dict[str, Any], list[str]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, [f"artifact_unavailable:{path.name}"]
    return (value, []) if isinstance(value, dict) else ({}, ["artifact_root_must_be_object"])


def _event_path_for(path: Path) -> Path | None:
    if path.is_file() and path.suffix.lower() == ".jsonl":
        return path
    candidates = []
    if path.is_file():
        candidates.append(path.with_name("events.jsonl"))
    else:
        candidates.append(path / "events.jsonl")
        candidates.extend(sorted(path.glob("*.jsonl")))
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _artifact_path_for(path: Path) -> Path | None:
    if path.is_file() and path.suffix.lower() == ".json":
        return path
    if path.is_dir():
        preferred = path / "validation_report.json"
        if preferred.is_file():
            return preferred
        candidates = sorted(path.glob("*.json"))
        return candidates[0] if candidates else None
    return None


def load_evaluation_input(path: str | Path, *, source: str = "auto") -> EvaluationInput:
    """Load a validation artifact, event JSONL, replay JSONL, or workspace.

    Directory discovery is intentionally small and deterministic: a
    validation report is preferred, then the lexicographically first JSON
    artifact; ``events.jsonl`` is selected when present. No files are written.
    """
    requested = Path(path)
    resolved = requested.resolve()
    warnings: list[str] = []
    artifact: dict[str, Any] = {}
    events: list[Event] = []
    artifact_path = _artifact_path_for(resolved)
    event_path = _event_path_for(resolved)
    if artifact_path is not None:
        artifact, artifact_warnings = _read_json(artifact_path)
        warnings.extend(artifact_warnings)
    if event_path is not None:
        events, event_warnings = load_events_from_jsonl(event_path)
        warnings.extend(event_warnings)
    if artifact_path is None and event_path is None:
        warnings.append("evaluation_input_not_found")
    label = source if source != "auto" else ("jsonl" if resolved.suffix.lower() == ".jsonl" else "artifact")
    return EvaluationInput(label, str(resolved), artifact, tuple(events), tuple(warnings))


def _reproducibility(events: tuple[Event, ...]) -> ReproducibilityReport:
    ids = [event.event_id for event in events]
    hashes = [event.replay_hash() for event in events]
    duplicate_ids = len(ids) - len(set(ids))
    stable_order = list(zip((event.occurred_at for event in events), ids)) == sorted(zip((event.occurred_at for event in events), ids))
    warnings: list[str] = []
    if duplicate_ids:
        warnings.append("duplicate_event_ids")
    if not stable_order:
        warnings.append("event_order_not_canonical")
    digest = hashlib.sha256("".join(hashes).encode()).hexdigest() if hashes else ""
    return ReproducibilityReport(
        event_count=len(events), unique_event_ids=len(set(ids)), duplicate_event_ids=duplicate_ids,
        replay_hash_count=len(hashes), replay_hash_digest=digest, replay_hash_available=bool(hashes),
        stable_event_order=stable_order, reproducible=bool(events) and not warnings, warnings=tuple(warnings),
    )


def _engine_evaluation(name: str, metrics: dict[str, Any], warnings: list[str], sample_size: int) -> EngineEvaluation:
    return EngineEvaluation(name, "insufficient_evidence" if sample_size == 0 else "measured_with_warnings" if warnings else "measured", sample_size, metrics, tuple(sorted(set(warnings))))


def evaluate_input(value: EvaluationInput, *, comparison: ComparisonReport | None = None) -> EvaluationReport:
    events = value.event_dicts()
    supplier, supplier_warnings, supplier_records = supplier_metrics(value.artifact, events)
    competition, competition_warnings, competition_records = competition_metrics(value.artifact, events)
    opportunity, opportunity_warnings, opportunity_scores, ranking = opportunity_metrics(value.artifact, events)
    research, research_warnings = research_metrics(value.artifact, events)
    margin, margin_warnings = margin_metrics(value.artifact, events)
    engines = (
        _engine_evaluation("supplier_evidence", supplier, supplier_warnings, len(supplier_records)),
        _engine_evaluation("competition_intelligence", competition, competition_warnings, len(competition_records)),
        _engine_evaluation("opportunity_scoring", opportunity, opportunity_warnings, len(opportunity_scores)),
        _engine_evaluation("research_portfolio", research, research_warnings, int(research.get("candidate_count", 0))),
        _engine_evaluation("margin_intelligence", margin, margin_warnings, 1 if margin else 0),
    )
    engine_dicts = {engine.engine: engine.metrics for engine in engines}
    overall, overall_warnings, blockers = overall_metrics(engine_dicts, events)
    reproducibility = _reproducibility(value.events)
    warnings = tuple(sorted(set((*value.warnings, *overall_warnings, *reproducibility.warnings))))
    blockers = tuple(sorted(set(blockers)))
    workspace_id = next((event.workspace_id for event in value.events if event.workspace_id), None)
    workspace_id = workspace_id or str(value.artifact.get("workspace_id") or value.artifact.get("commerce_mvp_run", {}).get("workspace_id") or "") or None
    run_id = str(value.artifact.get("commerce_mvp_run", {}).get("run_id") or next((event.correlation_id for event in value.events if event.correlation_id), "evaluation-input"))
    fingerprint = source_fingerprint(value.artifact, events)
    report_id = "commerce-evaluation-" + fingerprint[:20]
    return EvaluationReport(
        framework_version=FRAMEWORK_VERSION, report_id=report_id, workspace_id=workspace_id, run_id=run_id,
        input_kind=value.source, source_fingerprint=fingerprint, event_count=len(value.events), engines=engines,
        overall=overall, reproducibility=reproducibility, comparison=comparison, warnings=warnings, blockers=blockers,
    )


def _flatten_numeric(prefix: str, value: Any, output: dict[str, float]) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            _flatten_numeric(f"{prefix}.{key}" if prefix else str(key), item, output)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        output[prefix] = round(float(value), 6)


def _ranking_stability(baseline: list[str], current: list[str]) -> float | None:
    common = [item for item in baseline if item in set(current)]
    if not common:
        return None
    if len(common) == 1:
        return 1.0
    baseline_positions = {item: index for index, item in enumerate(baseline)}
    current_positions = {item: index for index, item in enumerate(current)}
    displacement = sum(abs(baseline_positions[item] - current_positions[item]) for item in common)
    maximum = len(common) * len(common)
    return round(max(0.0, 1.0 - displacement / maximum), 4)


def compare_evaluations(baseline: EvaluationReport, current: EvaluationReport) -> ComparisonReport:
    baseline_values: dict[str, float] = {}
    current_values: dict[str, float] = {}
    _flatten_numeric("overall", baseline.overall, baseline_values)
    _flatten_numeric("overall", current.overall, current_values)
    for engine in baseline.engines:
        _flatten_numeric(engine.engine, engine.metrics, baseline_values)
    for engine in current.engines:
        _flatten_numeric(engine.engine, engine.metrics, current_values)
    deltas: dict[str, float | None] = {}
    improved: list[str] = []
    worsened: list[str] = []
    unchanged: list[str] = []
    lower_is_better = {"overall.assumption_percentage"}
    for key in sorted(set(baseline_values) | set(current_values)):
        before = baseline_values.get(key)
        after = current_values.get(key)
        if before is None or after is None:
            deltas[key] = None
            continue
        delta = round(after - before, 6)
        deltas[key] = delta
        if delta == 0:
            unchanged.append(key)
        elif (delta < 0 if key in lower_is_better else delta > 0):
            improved.append(key)
        else:
            worsened.append(key)
    baseline_ranking = next((engine.metrics.get("ranking", []) for engine in baseline.engines if engine.engine == "opportunity_scoring"), [])
    current_ranking = next((engine.metrics.get("ranking", []) for engine in current.engines if engine.engine == "opportunity_scoring"), [])
    stability = _ranking_stability(list(baseline_ranking), list(current_ranking))
    return ComparisonReport(
        baseline_run_id=baseline.run_id, current_run_id=current.run_id, deltas=deltas,
        improved_metrics=tuple(improved), worsened_metrics=tuple(worsened), unchanged_metrics=tuple(unchanged),
        ranking_stability=stability,
        notes=("positive deltas are improvements except overall.assumption_percentage, where lower is better",),
    )


def evaluation_events(report: EvaluationReport, *, occurred_at: float = 0.0) -> list[Event]:
    """Map a report to canonical, read-only evaluation events."""
    metadata = {
        "evaluation_framework_version": report.framework_version,
        "dry_run": True, "read_only": True, "advisory": True, "non_authoritative": True,
        "manual_approval_required": True, "pii_redacted": True,
        "no_launch_authority": True, "no_spend_authority": True,
        "no_publish_authority": True, "no_store_mutation_authority": True,
        "no_inventory_mutation_authority": True, "no_payment_authority": True,
        "no_refund_authority": True, "no_fulfillment_authority": True,
        "no_customer_message_authority": True,
        "replay_certified": report.reproducibility.reproducible,
    }
    events: list[Event] = [Event(
        f"{report.report_id}:started", report.workspace_id, "commerce_evaluation", report.report_id,
        "commerce_evaluation_started", 1, occurred_at, correlation_id=report.run_id,
        source="evaluation.commerce", payload={"run_id": report.run_id, "event_count": report.event_count}, metadata=metadata,
    )]
    for index, engine in enumerate(report.engines, start=1):
        events.append(Event(
            f"{report.report_id}:{engine.engine}", report.workspace_id, "commerce_evaluation", report.report_id,
            "commerce_engine_evaluated", 1, occurred_at + index / 1000, correlation_id=report.run_id,
            source="evaluation.commerce", payload=engine.to_dict(), metadata=metadata,
        ))
    events.append(Event(
        f"{report.report_id}:completed", report.workspace_id, "commerce_evaluation", report.report_id,
        "commerce_evaluation_completed", 1, occurred_at + (len(report.engines) + 1) / 1000,
        correlation_id=report.run_id, source="evaluation.commerce", payload=report.to_dict(), metadata=metadata,
    ))
    return events


__all__ = ["EvaluationInput", "compare_evaluations", "evaluate_input", "evaluation_events", "load_evaluation_input"]
