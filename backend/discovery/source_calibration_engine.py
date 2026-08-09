from __future__ import annotations

import uuid

from .discovery_registry import get_discovery_registry
from .import_registry import get_import_registry
from .refinement_registry import get_refinement_registry
from .source_calibration import CalibrationRun, SourceUsefulnessSignal, build_source_calibration_profiles


def _sources_for_discovery(discovery, imports):
    names = list(getattr(discovery, "source_names", []) or [])
    jobs = [job for job in imports if job.source_name in names]
    if not names: names = sorted({job.source_name for job in imports})
    return [(name, next((job for job in jobs if job.source_name == name), None)) for name in names]


def derive_source_usefulness_signals(workspace_id="default", comparison_ids=None, import_ids=None):
    from .discovery_comparison import DiscoveryComparison
    discovery_registry = get_discovery_registry(); import_registry = get_import_registry(); refinement = get_refinement_registry()
    comparisons = [refinement.get_comparison(x) for x in comparison_ids] if comparison_ids else refinement.list_comparisons(workspace_id, 100)
    comparisons = [x for x in comparisons if x is not None and x.workspace_id == workspace_id]
    imports = [import_registry.get_import_job(x) for x in import_ids] if import_ids else import_registry.list_import_jobs(workspace_id=workspace_id, limit=500)
    imports = [x for x in imports if x is not None]
    signals = []
    for comparison in comparisons:
        current = discovery_registry.get_category_discovery(comparison.current_discovery_id); baseline = discovery_registry.get_category_discovery(comparison.baseline_discovery_id)
        source_pairs = _sources_for_discovery(current, imports) if current else []
        if not source_pairs: continue
        confidence = 0.8 if len(source_pairs) == 1 else 0.4
        for source_name, job in source_pairs:
            parser = job.parser_type if job else "unknown"
            source_type = job.source_type if job else "local_file"
            base = dict(workspace_id=workspace_id, source_name=source_name, source_type=source_type, parser_type=parser, related_import_id=job.import_id if job else "", baseline_discovery_id=comparison.baseline_discovery_id, current_discovery_id=comparison.current_discovery_id, comparison_id=comparison.comparison_id, confidence=confidence, weight=1.0, provenance={"method": "comparison_source_attribution", "ambiguous_source_mapping": len(source_pairs) > 1, "non_causal": True})
            if comparison.evidence_count_change > 0: signals.append(SourceUsefulnessSignal("signal_" + uuid.uuid4().hex[:16], signal_type="evidence_count_increase", entity_name="", value=comparison.evidence_count_change, rationale=["Current discovery contains more evidence records than baseline."], **base))
            for movement in comparison.category_movements:
                if movement.get("score_change", 0) > 0: signals.append(SourceUsefulnessSignal("signal_" + uuid.uuid4().hex[:16], signal_type="confidence_increase", entity_name=movement.get("category_name", ""), value=movement.get("score_change", 0), rationale=["Category score increased after the compared evidence set was included."], **base))
                if movement.get("rank_change", 0) > 0: signals.append(SourceUsefulnessSignal("signal_" + uuid.uuid4().hex[:16], signal_type="rank_improvement", entity_name=movement.get("category_name", ""), value=movement.get("rank_change", 0), rationale=["Category rank improved in the current recorded discovery."], **base))
                if movement.get("score_change", 0) < 0: signals.append(SourceUsefulnessSignal("signal_" + uuid.uuid4().hex[:16], signal_type="low_confidence_noise", entity_name=movement.get("category_name", ""), value=abs(movement.get("score_change", 0)), rationale=["Category score declined in the current recorded discovery; source attribution is non-causal."], **base))
            for change in comparison.recommendation_changes:
                if change.get("current") in {"investigate", "prioritize"} and change.get("baseline") in {"reject", "hold", "investigate"}: signals.append(SourceUsefulnessSignal("signal_" + uuid.uuid4().hex[:16], signal_type="recommendation_upgrade", entity_name=change.get("category_name", ""), value=1, rationale=["Category recommendation upgraded in the current recorded discovery."], **base))
            if job and job.records_rejected > max(1, job.records_imported): signals.append(SourceUsefulnessSignal("signal_" + uuid.uuid4().hex[:16], signal_type="unsupported_signal_rejection", entity_name="", value=job.records_rejected, rationale=["The import rejected more rows than it accepted."], **base))
            if job and any("duplicates_removed" in warning for warning in job.warnings): signals.append(SourceUsefulnessSignal("signal_" + uuid.uuid4().hex[:16], signal_type="duplicate_noise", entity_name="", value=1, rationale=["The import reported duplicate evidence removal."], **base))
    return signals


def run_source_calibration(workspace_id="default", comparison_ids=None, import_ids=None):
    signals = derive_source_usefulness_signals(workspace_id, comparison_ids, import_ids); profiles = build_source_calibration_profiles(signals); status = "completed" if signals else "partial"; summary = "Profiles summarize observed changes in persisted discovery comparisons." if signals else "Insufficient comparison records; run import-refine-compare after adding local evidence."
    recommendations = ["Collect at least one baseline and one current discovery comparison.", "Treat source attribution as indicative when multiple imports changed between runs."] if not signals else [f"Prioritize sources with positive observed signals: {', '.join(p.source_name for p in profiles if p.recommended_priority_adjustment > 0) or 'none'}.", "Keep source-specific limitations and provenance in every refinement cycle."]
    run = CalibrationRun("calibration_" + uuid.uuid4().hex[:16], workspace_id, "Source Usefulness Calibration", "Estimate which local evidence sources have been useful in recorded comparisons", signals, profiles, summary, recommendations, status, metadata={"non_causal": True, "signal_count": len(signals)})
    from .calibration_registry import get_calibration_registry
    registry = get_calibration_registry(); registry.register_signals(signals)
    for profile in profiles: registry.register_profile(profile)
    registry.register_calibration_run(run)
    return run
