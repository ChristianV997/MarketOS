from __future__ import annotations

from .discovery_comparison import compare_category_discoveries
from .discovery_registry import get_discovery_registry
from .evidence_gap import analyze_evidence_gaps
from .import_recommendation import build_import_recommendation_plan
from .import_templates import create_templates_for_plan
from .acquisition_plan import build_acquisition_plan_from_recommendation
from .acquisition_registry import get_acquisition_registry
from .connector_stubs import get_connector_stub
from .source_calibration_engine import run_source_calibration
from .market_discovery_runner import run_market_discovery
from .refinement_registry import get_refinement_registry
from backend.obsidian.sync import sync_acquisition_plan_note, sync_connector_stub_note, sync_discovery_comparison_note, sync_refinement_cycle_note, sync_source_calibration_note


def run_refinement_cycle(workspace_id="default", discovery_id=None, hypothesis_run_id=None, create_templates=True, max_recommendations=8, refresh_pipeline=True):
    registry = get_refinement_registry(); calibration = run_source_calibration(workspace_id); analysis = analyze_evidence_gaps(workspace_id, discovery_id, hypothesis_run_id); registry.register_gap_analysis(analysis)
    plan = build_import_recommendation_plan(analysis, max_recommendations); registry.register_import_plan(plan)
    templates = create_templates_for_plan(plan) if create_templates else []
    for template in templates: registry.register_template(template)
    acquisition_plans = []
    acquisition_warnings = []
    for recommendation in plan.recommendations:
        try:
            acquisition = build_acquisition_plan_from_recommendation(recommendation, workspace_id)
            if create_templates:
                matching = next((x for x in templates if x.parser_type == acquisition.parser_type), None)
                if matching: acquisition.template_paths = [matching.file_path]
            get_acquisition_registry().register_plan(acquisition)
            stub = get_connector_stub(acquisition.parser_type); get_acquisition_registry().register_stub(stub)
            acquisition_plans.append(acquisition)
        except Exception as exc:
            acquisition_warnings.append(f"acquisition_plan_failed:{type(exc).__name__}")
    obsidian = sync_refinement_cycle_note(analysis, plan, templates)
    acquisition_obsidian = [sync_acquisition_plan_note(item) for item in acquisition_plans]
    stub_obsidian = [sync_connector_stub_note(get_connector_stub(item.parser_type)) for item in acquisition_plans]
    result = {"gap_analysis": analysis.to_dict(), "import_plan": plan.to_dict(), "templates": [x.to_dict() for x in templates], "acquisition_plans": [x.to_dict() for x in acquisition_plans], "calibration": calibration.to_dict(), "calibration_profiles_used": [x.to_dict() for x in calibration.profiles], "source_usefulness_summary": calibration.summary, "adjusted_import_recommendations": [x.to_dict() for x in plan.recommendations], "obsidian": obsidian, "calibration_obsidian": sync_source_calibration_note(calibration), "acquisition_obsidian": acquisition_obsidian, "stub_obsidian": stub_obsidian, "warnings": acquisition_warnings, "status": "completed"}
    if refresh_pipeline:
        try:
            from .opportunity_pipeline_builder import refresh_opportunity_pipeline
            result["opportunity_pipeline"] = refresh_opportunity_pipeline(workspace_id, discovery_id, hypothesis_run_id)
            result["opportunity_snapshot_id"] = result["opportunity_pipeline"].get("snapshot_id")
        except Exception as exc:
            result["warnings"].append(f"opportunity_pipeline_refresh_failed:{type(exc).__name__}")
    return result


def run_import_refine_compare(workspace_id="default", import_paths=None, parser_type_by_path=None, source_name_by_path=None, baseline_discovery_id=None, max_categories=10, max_hypotheses=20):
    before = get_discovery_registry().get_category_discovery(baseline_discovery_id) if baseline_discovery_id else None
    result = run_market_discovery(workspace_id=workspace_id, import_paths=import_paths or [], parser_type_by_path=parser_type_by_path, source_name_by_path=source_name_by_path, max_categories=max_categories, max_hypotheses=max_hypotheses, run_validation_services=False)
    current = get_discovery_registry().get_category_discovery(result.get("discovery", {}).get("discovery_id", ""))
    comparison = compare_category_discoveries(before, current, workspace_id) if current else None
    if comparison:
        get_refinement_registry().register_comparison(comparison); result["comparison"] = comparison.to_dict(); result["comparison_obsidian"] = sync_discovery_comparison_note(comparison)
    refined = run_refinement_cycle(workspace_id, current.discovery_id if current else None, max_recommendations=8, create_templates=True)
    result.update({"gap_analysis": refined["gap_analysis"], "import_plan": refined["import_plan"], "templates": refined["templates"], "acquisition_plans": refined["acquisition_plans"], "calibration": refined["calibration"], "calibration_profiles_used": refined["calibration_profiles_used"], "source_usefulness_summary": refined["source_usefulness_summary"], "adjusted_import_recommendations": refined["adjusted_import_recommendations"], "refinement_obsidian": refined["obsidian"], "calibration_obsidian": refined["calibration_obsidian"], "acquisition_obsidian": refined["acquisition_obsidian"], "stub_obsidian": refined["stub_obsidian"]})
    return result
