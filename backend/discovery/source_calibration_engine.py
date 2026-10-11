from __future__ import annotations

import json
import uuid
from collections import Counter
from typing import Any

from .discovery_registry import get_discovery_registry
from .import_registry import get_import_registry
from .refinement_registry import get_refinement_registry
from .source_calibration import (
    CALIBRATION_POLICY_VERSION,
    EXCLUSION_AMBIGUOUS,
    EXCLUSION_AMBIGUOUS_IMPORT,
    EXCLUSION_STALE,
    EXCLUSION_UNMATCHED,
    MAX_ORDERING_EFFECT,
    MIN_COMPARISONS_FOR_ADJUSTMENT,
    MIN_ELIGIBLE_SIGNALS_FOR_ADJUSTMENT,
    STALE_AFTER_SECONDS,
    CalibrationRun,
    SourceUsefulnessSignal,
    build_source_calibration_profiles,
    signal_order_key,
)

__all__ = ["build_source_calibration_profiles", "derive_source_usefulness_signals", "run_source_calibration"]


_DUPLICATE = object()  # marks a source name that more than one import job carries


def _signal_id(**identity: Any) -> str:
    # Content-derived, so repeated runs over the same comparisons produce the same ids and registry writes overwrite instead of accumulating.
    return "signal_" + uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str)).hex[:16]


def _attribute(names: list[str], jobs: dict[str, Any]) -> list[tuple[str, Any, str, str]]:
    """Return (source_name, import_job, attribution, exclusion_reason) for each source a comparison names.

    A single named source is attributable only when exactly one import job carries it. With several named
    sources, the comparison's change cannot be split between them, so every source is excluded.
    """
    result = []
    for name in names:
        job = jobs.get(name)
        if len(names) > 1:
            attribution = EXCLUSION_AMBIGUOUS
        elif job is None:
            attribution = EXCLUSION_UNMATCHED
        elif job is _DUPLICATE:
            attribution = EXCLUSION_AMBIGUOUS_IMPORT
        else:
            attribution = "single_source"
        result.append((name, job if job is not _DUPLICATE else None, attribution, "" if attribution == "single_source" else attribution))
    return result


def _derive(workspace_id, comparison_ids, import_ids, as_of):
    discovery_registry = get_discovery_registry()
    import_registry = get_import_registry()
    refinement = get_refinement_registry()
    comparisons = [refinement.get_comparison(x) for x in comparison_ids] if comparison_ids else refinement.list_comparisons(workspace_id, 100)
    comparisons = sorted((x for x in comparisons if x is not None and x.workspace_id == workspace_id), key=lambda x: (x.created_at, x.comparison_id))
    # Reference time comes from the data unless the caller supplies one: no wall-clock input, so identical inputs give identical output.
    reference = float(as_of) if as_of is not None else max((x.created_at for x in comparisons), default=0.0)
    jobs = [import_registry.get_import_job(x) for x in import_ids] if import_ids else import_registry.list_import_jobs(workspace_id=workspace_id, limit=500)
    jobs_by_source: dict[str, Any] = {}
    for job in sorted((j for j in jobs if j is not None and j.workspace_id == workspace_id), key=lambda j: j.import_id):
        jobs_by_source[job.source_name] = _DUPLICATE if job.source_name in jobs_by_source else job
    exclusions: Counter[str] = Counter()
    considered: dict[str, Any] = {}
    signals: list[SourceUsefulnessSignal] = []
    for comparison in comparisons:
        current = discovery_registry.get_category_discovery(comparison.current_discovery_id)
        baseline = discovery_registry.get_category_discovery(comparison.baseline_discovery_id) if comparison.baseline_discovery_id else None
        if current is None:
            exclusions["current_discovery_unavailable"] += 1
            continue
        if getattr(current, "workspace_id", None) != workspace_id:
            exclusions["cross_workspace_discovery"] += 1
            continue
        if baseline is None:
            exclusions["baseline_missing"] += 1
            continue
        if getattr(baseline, "workspace_id", None) != workspace_id:
            exclusions["cross_workspace_discovery"] += 1
            continue
        names = sorted(set(current.source_names or []))
        if not names:
            exclusions["source_unattributed"] += 1
            continue
        stale = (reference - comparison.created_at) > STALE_AFTER_SECONDS
        for source_name, job, attribution, exclusion in _attribute(names, jobs_by_source):
            considered.setdefault(source_name, job)
            reason = EXCLUSION_STALE if stale else exclusion
            if reason:
                exclusions[reason] += 1
            base = dict(
                workspace_id=workspace_id, source_name=source_name, source_type=job.source_type if job else "unknown",
                parser_type=job.parser_type if job else "unknown", related_import_id=job.import_id if job else "",
                baseline_discovery_id=comparison.baseline_discovery_id, current_discovery_id=comparison.current_discovery_id,
                comparison_id=comparison.comparison_id, confidence=0.8 if attribution == "single_source" else 0.4, weight=1.0,
                created_at=comparison.created_at, attribution=attribution, exclusion_reason=reason,
            )

            def add(signal_type, entity_name, value, rationale):
                identity = dict(base, signal_type=signal_type, entity_name=entity_name, value=value)
                signals.append(SourceUsefulnessSignal(
                    _signal_id(**identity), signal_type=signal_type, entity_name=entity_name, value=value, rationale=[rationale],
                    provenance={"method": "comparison_source_attribution", "non_causal": True, "policy_version": CALIBRATION_POLICY_VERSION},
                    **base,
                ))

            if comparison.evidence_count_change > 0:
                add("evidence_count_increase", "", comparison.evidence_count_change, "Current discovery contains more evidence records than baseline.")
            for movement in comparison.category_movements:
                name_ = movement.get("category_name", "")
                if movement.get("score_change", 0) > 0:
                    add("confidence_increase", name_, movement.get("score_change", 0), "Category score increased after the compared evidence set was included.")
                if movement.get("rank_change", 0) > 0:
                    add("rank_improvement", name_, movement.get("rank_change", 0), "Category rank improved in the current recorded discovery.")
                if movement.get("score_change", 0) < 0:
                    add("low_confidence_noise", name_, abs(movement.get("score_change", 0)), "Category score declined in the current recorded discovery; source attribution is non-causal.")
            for change in comparison.recommendation_changes:
                if change.get("current") in {"investigate", "prioritize"} and change.get("baseline") in {"reject", "hold", "investigate"}:
                    add("recommendation_upgrade", change.get("category_name", ""), 1, "Category recommendation upgraded in the current recorded discovery.")
    # Import-quality signals describe one import job, so they are emitted once per source rather than once per comparison.
    for source_name in sorted(considered):
        job = considered[source_name]
        if job is None or job is _DUPLICATE:
            continue
        quality = []
        if job.records_rejected > max(1, job.records_imported):
            quality.append(("unsupported_signal_rejection", job.records_rejected, "The import rejected more rows than it accepted."))
        if any("duplicates_removed" in warning for warning in job.warnings):
            quality.append(("duplicate_noise", 1, "The import reported duplicate evidence removal."))
        for signal_type, value, rationale in quality:
            identity = dict(workspace_id=workspace_id, source_name=source_name, parser_type=job.parser_type, import_id=job.import_id, signal_type=signal_type, value=value)
            signals.append(SourceUsefulnessSignal(_signal_id(**identity), workspace_id, source_name, job.source_type, job.parser_type, related_import_id=job.import_id, signal_type=signal_type, value=value, confidence=0.8, weight=1.0, rationale=[rationale], created_at=reference, attribution="import_quality", provenance={"method": "import_quality", "non_causal": True, "policy_version": CALIBRATION_POLICY_VERSION}))
    return sorted(signals, key=signal_order_key), dict(sorted(exclusions.items())), reference, comparisons


def derive_source_usefulness_signals(workspace_id="default", comparison_ids=None, import_ids=None, *, as_of=None):
    return _derive(workspace_id, comparison_ids, import_ids, as_of)[0]


def run_source_calibration(workspace_id="default", comparison_ids=None, import_ids=None, *, as_of=None):
    signals, exclusions, reference, comparisons = _derive(workspace_id, comparison_ids, import_ids, as_of)
    profiles = build_source_calibration_profiles(signals)
    observed = [p for p in profiles if p.evidence_status == "observed"]
    status = "completed" if observed else "partial"
    if observed:
        summary = "Observed profiles summarize changes in persisted discovery comparisons that met the sample and attribution policy."
        recommendations = [
            f"Observed profiles may reorder import recommendations by at most {MAX_ORDERING_EFFECT:g} points; critical and high gaps keep their floor.",
            "Sources with an observed positive net signal: " + (", ".join(p.source_name for p in observed if p.recommended_priority_adjustment > 0) or "none") + ".",
            "Keep source-specific limitations and provenance in every refinement cycle.",
        ]
    else:
        summary = "No source met the calibration policy; comparisons are recorded but import ordering is unchanged."
        recommendations = [
            f"Collect at least {MIN_ELIGIBLE_SIGNALS_FOR_ADJUSTMENT} eligible signals across {MIN_COMPARISONS_FOR_ADJUSTMENT} single-source comparisons per source.",
            "Run import-refine-compare after adding local evidence, with one source per discovery where possible.",
        ]
    if exclusions:
        recommendations.append("Excluded from calibration: " + ", ".join(f"{reason}={count}" for reason, count in exclusions.items()) + ".")
    identity = {"workspace_id": workspace_id, "reference_time": reference, "policy": CALIBRATION_POLICY_VERSION, "signal_ids": [s.signal_id for s in signals], "comparison_ids": [c.comparison_id for c in comparisons]}
    run_id = "calibration_" + uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(identity, sort_keys=True, separators=(",", ":"))).hex[:16]
    metadata = {
        "non_causal": True, "policy_version": CALIBRATION_POLICY_VERSION, "signal_count": len(signals),
        "eligible_signal_count": sum(1 for s in signals if s.eligible), "exclusions": exclusions,
        "reference_time": reference, "ordering_effect_bound": MAX_ORDERING_EFFECT,
        "min_eligible_signals": MIN_ELIGIBLE_SIGNALS_FOR_ADJUSTMENT, "min_comparisons": MIN_COMPARISONS_FOR_ADJUSTMENT,
        "stale_after_seconds": STALE_AFTER_SECONDS,
    }
    run = CalibrationRun(run_id, workspace_id, "Source Usefulness Calibration", "Estimate which local evidence sources have been useful in recorded comparisons", signals, profiles, summary, recommendations, status, created_at=reference, metadata=metadata)
    from .calibration_registry import get_calibration_registry
    registry = get_calibration_registry()
    registry.register_signals(signals)
    for profile in profiles:
        registry.register_profile(profile)
    registry.register_calibration_run(run)
    return run
