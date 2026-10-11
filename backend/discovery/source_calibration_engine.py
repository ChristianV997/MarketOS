from __future__ import annotations

from collections import Counter
from typing import Any, Callable, NamedTuple

from .discovery_registry import get_discovery_registry
from .import_registry import get_import_registry
from .refinement_registry import get_refinement_registry
from .source_calibration import (
    CALIBRATION_POLICY_VERSION,
    EXCLUSION_AMBIGUOUS,
    EXCLUSION_AMBIGUOUS_IMPORT,
    EXCLUSION_IMPORT_QUALITY,
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
    stable_id,
)

__all__ = ["build_source_calibration_profiles", "derive_source_usefulness_signals", "run_source_calibration"]

COMPARISON_WINDOW = 500  # the refinement registry's maximum for one listing
IMPORT_WINDOW = 500  # the import registry's maximum for one listing
_DUPLICATE = object()  # a source name carried by more than one import job in the workspace


class _Derived(NamedTuple):
    signals: list
    exclusions: dict
    reference: float
    comparisons: list
    comparison_window_truncated: bool
    import_window_truncated: bool


def _attribute(names: list[str], job_for: Callable[[str], Any], selected: set[str] | None) -> list[tuple[str, Any, str]]:
    """Return (source_name, import_job_or_None, attribution) for each source a comparison touches.

    A change is single-source only when the baseline and current discoveries together name exactly one source,
    and that source has exactly one import job in the workspace, and the caller selected that job. Otherwise the
    change cannot be split between sources, so it is recorded as excluded.
    """
    result = []
    for name in names:
        raw = job_for(name)
        job = None if raw is None or raw is _DUPLICATE or (selected is not None and raw.import_id not in selected) else raw
        if len(names) > 1:
            attribution = EXCLUSION_AMBIGUOUS
        elif raw is _DUPLICATE:
            attribution = EXCLUSION_AMBIGUOUS_IMPORT
        elif job is None:
            attribution = EXCLUSION_UNMATCHED
        else:
            attribution = "single_source"
        result.append((name, job, attribution))
    return result


def _derive(workspace_id, comparison_ids, import_ids, as_of):
    discovery_registry = get_discovery_registry()
    import_registry = get_import_registry()
    refinement = get_refinement_registry()
    exclusions: Counter[str] = Counter()
    if comparison_ids:
        comparisons = []
        for comparison_id in dict.fromkeys(comparison_ids):  # a repeated id is one comparison, not two
            comparison = refinement.get_comparison(comparison_id)
            if comparison is None:
                exclusions["comparison_not_found"] += 1
            elif comparison.workspace_id != workspace_id:
                exclusions["cross_workspace_comparison"] += 1
            else:
                comparisons.append(comparison)
        truncated = False
    else:
        comparisons = refinement.list_comparisons(workspace_id, COMPARISON_WINDOW)
        truncated = len(comparisons) >= COMPARISON_WINDOW  # judged on what the registry returned, before any as_of filter
    selected_comparisons = []
    for comparison in comparisons:
        if comparison is None or comparison.workspace_id != workspace_id:
            continue
        if as_of is not None and comparison.created_at > float(as_of):
            exclusions["after_as_of"] += 1
            continue
        selected_comparisons.append(comparison)
    comparisons = sorted({c.comparison_id: c for c in selected_comparisons}.values(), key=lambda x: (x.created_at, x.comparison_id))
    # The reference time comes from the data unless the caller supplies one, so identical inputs give identical output.
    reference = float(as_of) if as_of is not None else max((x.created_at for x in comparisons), default=0.0)
    selected = set(import_ids) if import_ids else None
    def visible(job) -> bool:
        return job is not None and job.workspace_id == workspace_id and (as_of is None or float(job.created_at) <= float(as_of))

    raw_jobs = import_registry.list_import_jobs(workspace_id=workspace_id, limit=IMPORT_WINDOW)
    import_truncated = len(raw_jobs) >= IMPORT_WINDOW  # judged before the as_of filter, so a full window is never read as complete
    all_jobs = [j for j in raw_jobs if visible(j)]
    job_cache: dict[str, Any] = {}
    if not import_truncated:
        # Every import is in view, so duplicate names come from this one pass; a name not in it has no import.
        for job in sorted(all_jobs, key=lambda j: j.import_id):
            job_cache[job.source_name] = _DUPLICATE if job.source_name in job_cache else job

    def job_for(source_name: str) -> Any:
        if source_name not in job_cache:
            if not import_truncated:
                job_cache[source_name] = None
            else:
                # With a full window, an exact per-source query finds a clash however many other imports exist.
                found = [j for j in import_registry.list_import_jobs(workspace_id=workspace_id, source_name=source_name, limit=50) if visible(j) and j.source_name == source_name]
                job_cache[source_name] = _DUPLICATE if len(found) > 1 else (found[0] if found else None)
        return job_cache[source_name]

    signals: list[SourceUsefulnessSignal] = []
    for comparison in comparisons:
        current = discovery_registry.get_category_discovery(comparison.current_discovery_id)
        baseline = discovery_registry.get_category_discovery(comparison.baseline_discovery_id) if comparison.baseline_discovery_id else None
        if current is None:
            exclusions["current_discovery_unavailable"] += 1
            continue
        if baseline is None:
            exclusions["baseline_missing"] += 1
            continue
        if getattr(current, "workspace_id", None) != workspace_id or getattr(baseline, "workspace_id", None) != workspace_id:
            exclusions["cross_workspace_discovery"] += 1
            continue
        # Both sides count: a source present in the baseline and dropped from the current is still a confound.
        names = sorted(set(current.source_names or []) | set(baseline.source_names or []))
        if not names:
            exclusions["source_unattributed"] += 1
            continue
        stale = (reference - comparison.created_at) > STALE_AFTER_SECONDS
        for source_name, job, attribution in _attribute(names, job_for, selected):
            reason = EXCLUSION_STALE if stale else ("" if attribution == "single_source" else attribution)
            if reason:
                exclusions[reason] += 1
            base = dict(
                workspace_id=workspace_id, source_name=source_name, source_type=job.source_type if job else "unknown",
                parser_type=job.parser_type if job else "unknown", related_import_id=job.import_id if job else "",
                baseline_discovery_id=comparison.baseline_discovery_id, current_discovery_id=comparison.current_discovery_id,
                comparison_id=comparison.comparison_id, confidence=0.8 if attribution == "single_source" else 0.4, weight=1.0,
                created_at=comparison.created_at, attribution=attribution, exclusion_reason=reason,
            )

            def add(signal_type, entity_name, value, rationale, ordinal=0):
                # A position in the comparison keeps two identical entries as two signals, not one.
                entity_name = "" if entity_name is None else str(entity_name)
                identity = dict(base, signal_type=signal_type, entity_name=entity_name, value=value, ordinal=ordinal)
                signals.append(SourceUsefulnessSignal(
                    stable_id("signal_", identity), signal_type=signal_type, entity_name=entity_name, value=value, rationale=[rationale],
                    provenance={"method": "comparison_source_attribution", "non_causal": True, "policy_version": CALIBRATION_POLICY_VERSION},
                    **base,
                ))

            if comparison.evidence_count_change > 0:
                add("evidence_count_increase", "", comparison.evidence_count_change, "Current discovery contains more evidence records than baseline.")
            for position, movement in enumerate(comparison.category_movements):
                name_ = movement.get("category_name", "")
                if movement.get("score_change", 0) > 0:
                    add("confidence_increase", name_, movement.get("score_change", 0), "Category score increased after the compared evidence set was included.", position)
                if movement.get("rank_change", 0) > 0:
                    add("rank_improvement", name_, movement.get("rank_change", 0), "Category rank improved in the current recorded discovery.", position)
                if movement.get("score_change", 0) < 0:
                    add("low_confidence_noise", name_, abs(movement.get("score_change", 0)), "Category score declined in the current recorded discovery; source attribution is non-causal.", position)
            for position, change in enumerate(comparison.recommendation_changes):
                if change.get("current") in {"investigate", "prioritize"} and change.get("baseline") in {"reject", "hold", "investigate"}:
                    add("recommendation_upgrade", change.get("category_name", ""), 1, "Category recommendation upgraded in the current recorded discovery.", position)
    # Import-quality facts are recorded for every resolvable import in the workspace, but they never drive an adjustment.
    for job in sorted(all_jobs, key=lambda j: j.import_id):
        resolved = job_for(job.source_name)
        if resolved is None or resolved is _DUPLICATE or resolved.import_id != job.import_id:
            continue
        if selected is not None and job.import_id not in selected:
            continue
        quality = []
        if job.records_rejected > max(1, job.records_imported):
            quality.append(("unsupported_signal_rejection", job.records_rejected, "The import rejected more rows than it accepted."))
        if any("duplicates_removed" in warning for warning in job.warnings):
            quality.append(("duplicate_noise", 1, "The import reported duplicate evidence removal."))
        for signal_type, value, rationale in quality:
            identity = dict(workspace_id=workspace_id, source_name=job.source_name, parser_type=job.parser_type, import_id=job.import_id, signal_type=signal_type, value=value)
            signals.append(SourceUsefulnessSignal(
                stable_id("signal_", identity), workspace_id, job.source_name, job.source_type, job.parser_type, related_import_id=job.import_id,
                signal_type=signal_type, value=value, confidence=0.8, weight=1.0, rationale=[rationale], created_at=reference,
                attribution="import_quality", exclusion_reason=EXCLUSION_IMPORT_QUALITY,
                provenance={"method": "import_quality_fact", "non_causal": True, "policy_version": CALIBRATION_POLICY_VERSION},
            ))
            exclusions[EXCLUSION_IMPORT_QUALITY] += 1
    unique = {}
    for signal in signals: unique.setdefault(signal.signal_id, signal)  # equal ids are the same evidence, however many times it was listed
    return _Derived(sorted(unique.values(), key=signal_order_key), dict(sorted(exclusions.items())), reference, comparisons, truncated, import_truncated)


def derive_source_usefulness_signals(workspace_id="default", comparison_ids=None, import_ids=None, *, as_of=None):
    return _derive(workspace_id, comparison_ids, import_ids, as_of).signals


def run_source_calibration(workspace_id="default", comparison_ids=None, import_ids=None, *, as_of=None):
    derived = _derive(workspace_id, comparison_ids, import_ids, as_of)
    signals, exclusions, reference, comparisons, truncated, import_truncated = derived
    profiles = build_source_calibration_profiles(signals)
    observed = [p for p in profiles if p.evidence_status == "observed"]
    scoped = bool(comparison_ids or import_ids)
    incomplete_workspace_window = not scoped and (truncated or import_truncated)
    # With nothing in view (for example, the refinement registry was reset), the run is recorded and existing state is kept.
    nothing_in_view = not scoped and not comparisons
    status = "completed" if observed else "partial"
    if nothing_in_view or incomplete_workspace_window:
        profiles = []
        status = "partial"
    if observed and scoped:
        summary = "Observed profiles from this scoped run are recorded for review; they do not change import ordering."
        recommendations = [
            "Only a workspace-wide run updates the profiles that reorder import recommendations.",
            "Keep source-specific limitations and provenance in every refinement cycle.",
        ]
    elif observed:
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
    if scoped:
        recommendations.append("This run was scoped to selected comparisons or imports: it is recorded, but it did not replace the workspace profiles that drive recommendations.")
    if truncated:
        recommendations.append(f"Only the {COMPARISON_WINDOW} most recently registered comparisons were read; older ones are not counted.")
    if import_truncated:
        recommendations.append(f"Only the {IMPORT_WINDOW} most recently registered imports were read; older ones are not counted.")
    if incomplete_workspace_window:
        recommendations.append("The workspace calibration window was incomplete; existing profiles were preserved and no replacement profile was made active.")
    if exclusions:
        recommendations.append("Excluded from calibration: " + ", ".join(f"{reason}={count}" for reason, count in exclusions.items()) + ".")
    run_id = stable_id("calibration_", {"workspace_id": workspace_id, "reference_time": reference, "policy": CALIBRATION_POLICY_VERSION, "signal_ids": [s.signal_id for s in signals], "comparison_ids": [c.comparison_id for c in comparisons], "requested_comparisons": sorted(comparison_ids or []), "requested_imports": sorted(import_ids or []), "as_of": as_of, "scoped": scoped})
    metadata = {
        "non_causal": True, "policy_version": CALIBRATION_POLICY_VERSION, "scope": "scoped" if scoped else "workspace",
        "signal_count": len(signals), "eligible_signal_count": sum(1 for s in signals if s.eligible), "exclusions": exclusions,
        "reference_time": reference, "comparison_window": COMPARISON_WINDOW, "comparison_window_truncated": truncated,
        "import_window": IMPORT_WINDOW, "import_window_truncated": import_truncated,
        "ordering_effect_bound": MAX_ORDERING_EFFECT, "min_eligible_signals": MIN_ELIGIBLE_SIGNALS_FOR_ADJUSTMENT,
        "min_comparisons": MIN_COMPARISONS_FOR_ADJUSTMENT, "stale_after_seconds": STALE_AFTER_SECONDS,
    }
    run = CalibrationRun(run_id, workspace_id, "Source Usefulness Calibration", "Estimate which local evidence sources have been useful in recorded comparisons", signals, profiles, summary, recommendations, status, created_at=reference, metadata=metadata)
    from .calibration_registry import get_calibration_registry
    registry = get_calibration_registry()
    # One write. A scoped run is recorded without touching workspace profiles; a workspace run retires profiles whose evidence has gone.
    if nothing_in_view:
        run.recommendations.append("No comparisons were in view, so the workspace profiles were kept as they were.")
    replace_profiles = not scoped and not nothing_in_view and not incomplete_workspace_window
    persisted = registry.record_run(signals, profiles, run, replace_workspace_profiles=replace_profiles)
    if not persisted:
        # Nothing was saved, so nothing from this run may be reported as in use.
        run.status = "partial"
        run.profiles = []
        run.summary = "The calibration state could not be written, so nothing from this run is in use."
        run.recommendations = ["The calibration state could not be written; this run cannot be retrieved later by its identifier, and workspace profiles were not changed."]
    return run
