"""Replay-driven, read-only evaluation logic for shadow features.

This module consumes canonical events only.  It neither imports flag managers
nor production decision engines, and it intentionally emits recommendations
instead of changing feature flags.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Iterable, Sequence

from backend.contracts.events import Event
from backend.events.replay_certification import (
    assert_no_live_authority,
    hash_sequence,
    load_canonical_jsonl,
    summarize_ledger,
    validate_event_sequence,
)

from .matrix import CORE_FEATURE_IDS, evaluation_matrix
from .models import (
    DELETE,
    KEEP_SHADOW,
    PROMOTE,
    REWORK,
    EvaluationMetric,
    EvaluationReport,
    EvidenceRequirement,
    SafetyMetric,
    ShadowFeatureEvaluation,
)


def _records(events: Sequence[Event], feature_id: str) -> list[Event]:
    return [
        event for event in events
        if event.aggregate_id == feature_id or event.payload.get("feature_id") == feature_id
    ]


def _payload(events: Sequence[Event]) -> dict:
    """Merge fixture observations deterministically; later observations win."""
    merged: dict = {}
    for event in sorted(events, key=lambda item: (item.occurred_at, item.event_id)):
        merged.update(event.payload)
    return merged


def _number(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _event_types(payload: dict, events: Sequence[Event]) -> set[str]:
    declared = payload.get("observed_event_types", [])
    return {str(value) for value in declared} | {event.event_type for event in events}


def _metric(payload: dict, requirement: EvidenceRequirement) -> EvaluationMetric:
    baseline = _number(payload.get("baseline_value"))
    candidate = _number(payload.get("candidate_value"))
    delta = candidate - baseline
    tolerance = abs(_number(payload.get("tolerance")))
    return EvaluationMetric(
        name=str(payload.get("primary_metric_name") or requirement.required_metric_names[0]),
        value=candidate,
        baseline_value=baseline,
        candidate_value=candidate,
        delta=delta,
        direction=str(payload.get("primary_direction") or "higher_is_better"),
        tolerance=tolerance,
        passed=delta >= -tolerance,
        notes=[str(note) for note in payload.get("metric_notes", [])],
    )


def _safety_metrics(payload: dict) -> list[SafetyMetric]:
    metrics = payload.get("safety_metrics", {})
    if not isinstance(metrics, dict):
        return []
    output: list[SafetyMetric] = []
    for name in sorted(metrics):
        item = metrics[name] if isinstance(metrics[name], dict) else {}
        baseline = _number(item.get("baseline"))
        candidate = _number(item.get("candidate"))
        maximum = abs(_number(item.get("max_tolerated_regression")))
        blocker = bool(item.get("blocker", False))
        output.append(SafetyMetric(
            name=str(name), baseline_value=baseline, candidate_value=candidate,
            max_tolerated_regression=maximum,
            passed=not blocker and candidate >= baseline - maximum,
            blocker=blocker,
            notes=[str(note) for note in item.get("notes", [])],
        ))
    return output


def _domain_blockers(feature_id: str, payload: dict, ledger: dict) -> list[str]:
    blockers = [str(item) for item in payload.get("explicit_blockers", [])]
    if feature_id == "attribution_reconciliation":
        ground_truth = _number(payload.get("ground_truth_revenue", ledger["recognized_revenue"]))
        candidate = _number(payload.get("candidate_reconciled_revenue"))
        if candidate > ground_truth + 0.000001:
            blockers.append("candidate_revenue_exceeds_order_ground_truth")
        if _number(payload.get("candidate_refund_coverage"), 1.0) < 1.0:
            blockers.append("candidate_missing_refund_coverage")
    elif feature_id == "capital_policy":
        if _number(payload.get("candidate_budget")) > _number(payload.get("budget_cap"), float("inf")):
            blockers.append("budget_cap_exceeded")
        if _number(payload.get("candidate_concentration")) > _number(payload.get("max_concentration"), float("inf")):
            blockers.append("concentration_cap_exceeded")
        if _number(payload.get("candidate_drawdown")) > _number(payload.get("max_drawdown"), float("inf")):
            blockers.append("drawdown_cap_exceeded")
        if bool(payload.get("allocates_to_blocked_opportunity")):
            blockers.append("allocation_to_blocked_opportunity")
    elif feature_id == "normalized_scoring":
        if _number(payload.get("dominant_term_share")) > _number(payload.get("max_term_share"), 0.70):
            blockers.append("unbounded_score_term_dominance")
        if bool(payload.get("unsupported_score_terms")):
            blockers.append("unsupported_score_terms")
    elif feature_id == "adaptive_risk":
        worse_context = bool(payload.get("worse_volatility_or_concentration"))
        if worse_context and _number(payload.get("candidate_spend_cap")) > _number(payload.get("baseline_spend_cap")):
            blockers.append("risk_cap_loosened_in_worse_context")
        if bool(payload.get("kill_switch_bypassed")):
            blockers.append("kill_switch_bypassed")
    elif feature_id == "supplier_geo_economics":
        profit = _number(payload.get("candidate_contribution_profit", ledger["contribution_profit"]))
        if bool(payload.get("recommends_expansion")) and profit < 0:
            blockers.append("expansion_with_negative_landed_contribution")
        if bool(payload.get("cheapest_cost_bias_with_poor_reliability")):
            blockers.append("cheapest_cost_bias_with_poor_reliability")
    elif feature_id == "calibration_regime_confidence":
        if _number(payload.get("confidence_delta")) > 0 and _number(payload.get("error_delta")) > 0:
            blockers.append("confidence_increased_while_error_worsened")
        if bool(payload.get("same_window_leakage")):
            blockers.append("same_window_calibration_leakage")
    return sorted(set(blockers))


def classify_evaluation(
    *, sample_size: int, requirement: EvidenceRequirement, metric: EvaluationMetric,
    safety_metrics: Sequence[SafetyMetric], blockers: Sequence[str], missing_events: Sequence[str],
) -> tuple[str, list[str]]:
    """Apply promotion policy.  Missing evidence and any risk remain conservative."""
    rationale: list[str] = []
    if blockers or any(not safety.passed or safety.blocker for safety in safety_metrics):
        return REWORK, ["safety_or_domain_blocker"]
    if missing_events:
        return KEEP_SHADOW, ["missing_required_events"]
    if sample_size < requirement.minimum_sample_size:
        return KEEP_SHADOW, ["insufficient_sample_size"]
    if metric.delta < -metric.tolerance:
        return DELETE, ["primary_metric_regression"]
    if not metric.passed:
        return KEEP_SHADOW, ["primary_metric_inconclusive"]
    rationale.append("minimum_sample_and_safety_requirements_satisfied")
    return PROMOTE, rationale


def evaluate_shadow_feature(
    events: Sequence[Event], feature_id: str, matrix: dict[str, EvidenceRequirement] | None = None,
    fixture_name: str = "events",
) -> ShadowFeatureEvaluation:
    matrix = matrix or evaluation_matrix()
    if feature_id not in matrix:
        raise ValueError(f"unsupported shadow feature: {feature_id}")
    requirement = matrix[feature_id]
    relevant = _records(events, feature_id)
    payload = _payload(relevant)
    sample_size = int(_number(payload.get("sample_size")))
    observed = _event_types(payload, relevant)
    missing_events = sorted(set(requirement.required_event_types) - observed)
    metric = _metric(payload, requirement)
    safety = _safety_metrics(payload)
    ledger = summarize_ledger(events)
    blockers = _domain_blockers(feature_id, payload, ledger)
    sequence_issues = validate_event_sequence(events)
    authority_violations = assert_no_live_authority(events)
    if sequence_issues:
        blockers.extend(f"event_sequence:{issue}" for issue in sequence_issues)
    if authority_violations:
        blockers.extend(f"live_authority:{issue}" for issue in authority_violations)
    classification, reasons = classify_evaluation(
        sample_size=sample_size, requirement=requirement, metric=metric,
        safety_metrics=safety, blockers=blockers, missing_events=missing_events,
    )
    warnings = [f"missing_event:{event_type}" for event_type in missing_events]
    confidence = "high" if classification == PROMOTE else "moderate" if sample_size >= requirement.minimum_sample_size else "low"
    recommendation = {
        PROMOTE: "Certification-only result: eligible for human-reviewed promotion planning; do not flip a flag.",
        KEEP_SHADOW: "Continue shadow collection; do not alter production behavior.",
        REWORK: "Rework candidate safety or data logic before collecting more evidence.",
        DELETE: "Retire or redesign the candidate; do not promote it.",
    }[classification]
    return ShadowFeatureEvaluation(
        feature_id=feature_id, classification=classification, fixture_name=fixture_name,
        sample_size=sample_size, confidence_level=confidence, primary_metrics=[metric],
        safety_metrics=safety, blockers=sorted(set(blockers)), warnings=warnings,
        evidence_event_ids=[event.event_id for event in relevant], replay_hashes=hash_sequence(relevant),
        recommendation=recommendation, rationale=reasons, requirement=requirement,
    )


def evaluate_all_shadow_features(events: Sequence[Event], matrix: dict[str, EvidenceRequirement] | None = None, fixture_name: str = "events") -> list[ShadowFeatureEvaluation]:
    matrix = matrix or evaluation_matrix()
    present = {str(event.payload.get("feature_id")) for event in events if event.payload.get("feature_id")}
    return [evaluate_shadow_feature(events, feature, matrix, fixture_name) for feature in CORE_FEATURE_IDS if feature in present]


def build_shadow_evaluation_report(paths_or_events: Iterable[Path | str] | Sequence[Event]) -> EvaluationReport:
    """Build one deterministic report; each fixture is independently evaluated."""
    source = list(paths_or_events)
    evaluations: list[ShadowFeatureEvaluation] = []
    fixtures: list[str] = []
    if source and isinstance(source[0], Event):
        events = list(source)  # type: ignore[arg-type]
        evaluations.extend(evaluate_all_shadow_features(events))
        fixtures.append("events")
        latest_time = max((event.occurred_at for event in events), default=0.0)
    else:
        latest_time = 0.0
        for item in sorted(Path(path) for path in source):
            events = load_canonical_jsonl(item)
            fixtures.append(item.name)
            latest_time = max(latest_time, max((event.occurred_at for event in events), default=0.0))
            evaluations.extend(evaluate_all_shadow_features(events, fixture_name=item.name))
    evaluations.sort(key=lambda item: (item.fixture_name, item.feature_id))
    counts = Counter(item.classification for item in evaluations)
    blockers = sorted({blocker for item in evaluations for blocker in item.blockers})
    readiness = {
        "promote_candidates": [item.feature_id for item in evaluations if item.classification == PROMOTE],
        "requires_human_review": [item.feature_id for item in evaluations if item.classification == PROMOTE],
        "production_mutation": False,
        "feature_flags_changed": False,
    }
    report_id = "shadow-evaluation-" + "-".join(str(len(evaluations)).zfill(2) for _ in [0])
    return EvaluationReport(
        report_id=report_id, generated_at=latest_time, fixtures_evaluated=fixtures, features=evaluations,
        summary_counts={key: counts.get(key, 0) for key in (PROMOTE, KEEP_SHADOW, REWORK, DELETE)},
        global_blockers=blockers, migration_readiness=readiness,
        recommended_next_actions=[
            "Keep all flags unchanged; this report is read-only certification evidence.",
            "Collect additional canonical shadow events for every KEEP_SHADOW result.",
            "Resolve REWORK/DELETE blockers before any human-reviewed promotion proposal.",
        ],
    )


def compare_legacy_candidate_metrics(events: Sequence[Event], feature_id: str) -> list[EvaluationMetric]:
    return evaluate_shadow_feature(events, feature_id).primary_metrics


def explain_evaluation(evaluation: ShadowFeatureEvaluation) -> list[str]:
    return [*evaluation.rationale, *evaluation.blockers, *evaluation.warnings]


def report_to_dict(report: EvaluationReport) -> dict:
    return report.to_dict()
