from __future__ import annotations

from .discovery_comparison import compare_category_discoveries
from .discovery_registry import get_discovery_registry
from .evidence_gap import analyze_evidence_gaps
from .import_recommendation import build_import_recommendation_plan
from .import_templates import create_templates_for_plan
from .market_discovery_runner import run_market_discovery
from .refinement_registry import get_refinement_registry
from backend.obsidian.sync import sync_discovery_comparison_note, sync_refinement_cycle_note


def run_refinement_cycle(workspace_id="default", discovery_id=None, hypothesis_run_id=None, create_templates=True, max_recommendations=8):
    registry = get_refinement_registry(); analysis = analyze_evidence_gaps(workspace_id, discovery_id, hypothesis_run_id); registry.register_gap_analysis(analysis)
    plan = build_import_recommendation_plan(analysis, max_recommendations); registry.register_import_plan(plan)
    templates = create_templates_for_plan(plan) if create_templates else []
    for template in templates: registry.register_template(template)
    obsidian = sync_refinement_cycle_note(analysis, plan, templates)
    return {"gap_analysis": analysis.to_dict(), "import_plan": plan.to_dict(), "templates": [x.to_dict() for x in templates], "obsidian": obsidian, "status": "completed"}


def run_import_refine_compare(workspace_id="default", import_paths=None, parser_type_by_path=None, source_name_by_path=None, baseline_discovery_id=None, max_categories=10, max_hypotheses=20):
    before = get_discovery_registry().get_category_discovery(baseline_discovery_id) if baseline_discovery_id else None
    result = run_market_discovery(workspace_id=workspace_id, import_paths=import_paths or [], parser_type_by_path=parser_type_by_path, source_name_by_path=source_name_by_path, max_categories=max_categories, max_hypotheses=max_hypotheses, run_validation_services=False)
    current = get_discovery_registry().get_category_discovery(result.get("discovery", {}).get("discovery_id", ""))
    comparison = compare_category_discoveries(before, current, workspace_id) if current else None
    if comparison:
        get_refinement_registry().register_comparison(comparison); result["comparison"] = comparison.to_dict(); result["comparison_obsidian"] = sync_discovery_comparison_note(comparison)
    refined = run_refinement_cycle(workspace_id, current.discovery_id if current else None, max_recommendations=8, create_templates=True)
    result.update({"gap_analysis": refined["gap_analysis"], "import_plan": refined["import_plan"], "templates": refined["templates"], "refinement_obsidian": refined["obsidian"]})
    return result
