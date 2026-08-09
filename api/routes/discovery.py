from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Query

from backend.discovery.discovery_registry import get_discovery_registry
from backend.discovery.acquisition_plan import build_acquisition_plan_from_recommendation
from backend.discovery.acquisition_registry import get_acquisition_registry
from backend.discovery.csv_ingestion import SUPPORTED_PARSERS
from backend.discovery.connector_stubs import get_connector_stub, list_connector_stubs
from backend.discovery.calibration_registry import get_calibration_registry
from backend.discovery.source_calibration_engine import run_source_calibration
from backend.discovery.evidence_normalizer import normalize_imported_evidence
from backend.discovery.import_registry import get_import_registry
from backend.discovery.market_discovery_runner import run_market_discovery
from backend.discovery.refinement_registry import get_refinement_registry
from backend.discovery.refinement_runner import run_import_refine_compare, run_refinement_cycle
from backend.obsidian.sync import sync_acquisition_plan_note, sync_connector_stub_note
from backend.obsidian.sync import sync_evidence_import_note
from backend.discovery.opportunity_registry import get_opportunity_registry
from backend.discovery.opportunity_pipeline_builder import refresh_opportunity_pipeline
from backend.discovery.opportunity_gates import evaluate_opportunity_gates
from backend.discovery.opportunity_pipeline import STAGES, TRANSITIONS, OpportunityStageTransition
from backend.discovery.validation_sprint_registry import get_validation_sprint_registry
from backend.discovery.validation_sprint_runner import run_validation_sprint

router = APIRouter(prefix="/api/discovery", tags=["discovery"])


@router.post("/source-calibration")
def source_calibration(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    try:
        run = run_source_calibration(str(payload.get("workspace_id", "default")), payload.get("comparison_ids"), payload.get("import_ids"))
        return {"status": run.status, "calibration": run.to_dict()}
    except Exception as exc:
        return {"status": "error", "error": "source_calibration_failed", "error_type": type(exc).__name__}


@router.get("/source-calibrations")
def source_calibrations(workspace_id: str | None = Query(None), limit: int = Query(50, ge=0, le=500)) -> dict[str, Any]:
    items = get_calibration_registry().list_calibration_runs(workspace_id, limit); return {"calibrations": [x.to_dict() for x in items], "count": len(items)}


@router.get("/source-calibrations/{calibration_id}")
def source_calibration_detail(calibration_id: str) -> dict[str, Any]:
    item = get_calibration_registry().get_calibration_run(calibration_id); return {"status": "not_found", "calibration_id": calibration_id} if item is None else {"calibration": item.to_dict()}


@router.get("/source-calibration/profiles")
def source_calibration_profiles(workspace_id: str | None = Query(None), parser_type: str | None = Query(None), limit: int = Query(100, ge=0, le=500)) -> dict[str, Any]:
    items = get_calibration_registry().list_profiles(workspace_id, parser_type, limit); return {"profiles": [x.to_dict() for x in items], "count": len(items)}


@router.get("/source-calibration/signals")
def source_calibration_signals(workspace_id: str | None = Query(None), source_name: str | None = Query(None), parser_type: str | None = Query(None), signal_type: str | None = Query(None), limit: int = Query(100, ge=0, le=1000)) -> dict[str, Any]:
    items = get_calibration_registry().list_signals(workspace_id, source_name, parser_type, signal_type, limit); return {"signals": [x.to_dict() for x in items], "count": len(items)}


@router.post("/acquisition-plans/from-import-plan")
def acquisition_plans_from_import_plan(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    try:
        import_plan = get_refinement_registry().get_import_plan(str(payload.get("import_plan_id", "")))
        if import_plan is None: return {"status": "not_found", "import_plan_id": payload.get("import_plan_id")}
        items = []
        for recommendation in import_plan.recommendations:
            item = build_acquisition_plan_from_recommendation(recommendation, str(payload.get("workspace_id", import_plan.workspace_id)))
            get_acquisition_registry().register_plan(item); stub = get_connector_stub(item.parser_type); get_acquisition_registry().register_stub(stub)
            items.append(item)
        return {"status": "completed", "acquisition_plans": [x.to_dict() for x in items]}
    except Exception as exc:
        return {"status": "error", "error": "acquisition_plan_creation_failed", "error_type": type(exc).__name__}


@router.get("/acquisition-plans")
def acquisition_plans(workspace_id: str | None = Query(None), parser_type: str | None = Query(None), status: str | None = Query(None), limit: int = Query(50, ge=0, le=500)) -> dict[str, Any]:
    items = get_acquisition_registry().list_plans(workspace_id, parser_type, status, limit); return {"acquisition_plans": [x.to_dict() for x in items], "count": len(items)}


@router.get("/acquisition-plans/{plan_id}")
def acquisition_plan(plan_id: str) -> dict[str, Any]:
    item = get_acquisition_registry().get_plan(plan_id); return {"status": "not_found", "plan_id": plan_id} if item is None else {"acquisition_plan": item.to_dict()}


@router.post("/acquisition-plans/{plan_id}/status")
def acquisition_plan_status(plan_id: str, payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    allowed = {"drafted", "ready_for_manual_export", "template_created", "imported", "superseded", "blocked"}
    item = get_acquisition_registry().get_plan(plan_id)
    status = str(payload.get("status", ""))
    if item is None: return {"status": "not_found", "plan_id": plan_id}
    if status not in allowed: return {"status": "blocked", "blocked_reasons": ["invalid_acquisition_plan_status"], "allowed_statuses": sorted(allowed)}
    item.status = status; get_acquisition_registry().update_plan(item); return {"status": "updated", "acquisition_plan": item.to_dict()}


@router.get("/source-playbooks")
def source_playbooks() -> dict[str, Any]:
    from backend.discovery.source_playbooks import _PLAYBOOKS
    from backend.discovery.source_playbooks import get_source_playbook
    return {"source_playbooks": [get_source_playbook(key) for key in sorted(_PLAYBOOKS)]}


@router.get("/source-playbooks/{parser_type}")
def source_playbook(parser_type: str) -> dict[str, Any]:
    try:
        from backend.discovery.source_playbooks import get_source_playbook
        return {"source_playbook": get_source_playbook(parser_type)}
    except ValueError:
        return {"status": "not_found", "parser_type": parser_type}


@router.get("/connector-stubs")
def connector_stubs() -> dict[str, Any]:
    return {"connector_stubs": [x.to_dict() for x in list_connector_stubs()]}


@router.get("/connector-stubs/{connector_name}")
def connector_stub(connector_name: str) -> dict[str, Any]:
    item = next((x for x in list_connector_stubs() if x.connector_name == connector_name), None)
    return {"status": "not_found", "connector_name": connector_name} if item is None else {"connector_stub": item.to_dict(), "obsidian": sync_connector_stub_note(item)}


@router.post("/refinement-cycle")
def refinement_cycle(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    try:
        return run_refinement_cycle(str(payload.get("workspace_id", "default")), payload.get("discovery_id"), payload.get("hypothesis_run_id"), bool(payload.get("create_templates", True)), min(max(int(payload.get("max_recommendations", 8)), 0), 20))
    except Exception as exc:
        return {"status": "error", "error": "refinement_cycle_failed", "error_type": type(exc).__name__}


@router.post("/import-refine-compare")
def import_refine_compare(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    try:
        imports = payload.get("imports") or []
        if not isinstance(imports, list) or len(imports) > 10: return {"status": "blocked", "blocked_reasons": ["import_count_limit_exceeded"]}
        paths = [str(item.get("input_path", "")) for item in imports if isinstance(item, dict)]
        parsers = {str(item.get("input_path", "")): str(item.get("parser_type", "generic_market_csv")) for item in imports if isinstance(item, dict)}
        sources = {str(item.get("input_path", "")): str(item.get("source_name", parsers.get(str(item.get("input_path", "")), "generic_market_csv"))) for item in imports if isinstance(item, dict)}
        return run_import_refine_compare(str(payload.get("workspace_id", "default")), paths, parsers, sources, payload.get("baseline_discovery_id"), min(max(int(payload.get("max_categories", 10)), 0), 50), min(max(int(payload.get("max_hypotheses", 20)), 0), 100))
    except Exception as exc:
        return {"status": "error", "error": "import_refine_compare_failed", "error_type": type(exc).__name__}


@router.get("/gap-analyses")
def gap_analyses(workspace_id: str | None = Query(None), limit: int = Query(50, ge=0, le=500)) -> dict[str, Any]:
    items = get_refinement_registry().list_gap_analyses(workspace_id, limit); return {"gap_analyses": [x.to_dict() for x in items], "count": len(items)}


@router.get("/gap-analyses/{analysis_id}")
def gap_analysis(analysis_id: str) -> dict[str, Any]:
    item = get_refinement_registry().get_gap_analysis(analysis_id); return {"status": "not_found", "analysis_id": analysis_id} if item is None else {"gap_analysis": item.to_dict()}


@router.get("/import-plans")
def import_plans(workspace_id: str | None = Query(None), limit: int = Query(50, ge=0, le=500)) -> dict[str, Any]:
    items = get_refinement_registry().list_import_plans(workspace_id, limit); return {"import_plans": [x.to_dict() for x in items], "count": len(items)}


@router.get("/import-plans/{plan_id}")
def import_plan(plan_id: str) -> dict[str, Any]:
    item = get_refinement_registry().get_import_plan(plan_id); return {"status": "not_found", "plan_id": plan_id} if item is None else {"import_plan": item.to_dict()}


@router.get("/import-templates")
def import_templates(parser_type: str | None = Query(None), limit: int = Query(100, ge=0, le=500)) -> dict[str, Any]:
    items = get_refinement_registry().list_templates(parser_type, limit); return {"templates": [x.to_dict() for x in items], "count": len(items)}


@router.get("/import-templates/{template_id}")
def import_template(template_id: str) -> dict[str, Any]:
    item = get_refinement_registry().get_template(template_id); return {"status": "not_found", "template_id": template_id} if item is None else {"template": item.to_dict()}


@router.get("/comparisons")
def comparisons(workspace_id: str | None = Query(None), limit: int = Query(50, ge=0, le=500)) -> dict[str, Any]:
    items = get_refinement_registry().list_comparisons(workspace_id, limit); return {"comparisons": [x.to_dict() for x in items], "count": len(items)}


@router.get("/comparisons/{comparison_id}")
def comparison(comparison_id: str) -> dict[str, Any]:
    item = get_refinement_registry().get_comparison(comparison_id); return {"status": "not_found", "comparison_id": comparison_id} if item is None else {"comparison": item.to_dict()}


@router.post("/import-evidence")
def import_evidence(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    try:
        parser = str(payload.get("parser_type", ""))
        if parser not in SUPPORTED_PARSERS:
            return {"status": "blocked", "blocked_reasons": ["unsupported_parser_type"]}
        result = normalize_imported_evidence(str(payload.get("input_path", "")), parser, str(payload.get("source_name", parser)), str(payload.get("workspace_id", "default")), payload.get("provenance"), min(max(int(payload.get("max_rows", 10000)), 1), 10000))
        get_import_registry().register_import_job(result.import_job)
        get_import_registry().register_source_quality(result.source_quality)
        if result.records: get_discovery_registry().register_evidence(result.records)
        return {**result.to_dict(), "obsidian": sync_evidence_import_note(result.import_job, result.source_quality, result)}
    except Exception as exc:
        return {"status": "error", "error": "evidence_import_failed", "error_type": type(exc).__name__}


@router.post("/import-and-run")
def import_and_run(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    try:
        imports = payload.get("imports") or []
        if not isinstance(imports, list) or len(imports) > 10:
            return {"status": "blocked", "blocked_reasons": ["import_count_limit_exceeded"]}
        paths = [str(item.get("input_path", "")) for item in imports if isinstance(item, dict)]
        parsers = {str(item.get("input_path", "")): str(item.get("parser_type", "generic_market_csv")) for item in imports if isinstance(item, dict)}
        sources = {str(item.get("input_path", "")): str(item.get("source_name", parsers.get(str(item.get("input_path", "")), "generic_market_csv"))) for item in imports if isinstance(item, dict)}
        return run_market_discovery(workspace_id=str(payload.get("workspace_id", "default")), title=str(payload.get("title", "Imported Market Discovery")), objective=str(payload.get("objective", "Rank categories from imported evidence")), import_paths=paths, parser_type_by_path=parsers, source_name_by_path=sources, max_categories=min(max(int(payload.get("max_categories", 10)), 0), 50), max_hypotheses=min(max(int(payload.get("max_hypotheses", 20)), 0), 100), run_validation_services=bool(payload.get("run_validation_services", True)))
    except Exception as exc:
        return {"status": "error", "error": "import_and_run_failed", "error_type": type(exc).__name__}


@router.get("/imports")
def imports(workspace_id: str | None = Query(None), source_name: str | None = Query(None), status: str | None = Query(None), limit: int = Query(50, ge=0, le=500)) -> dict[str, Any]:
    items = get_import_registry().list_import_jobs(workspace_id, source_name, status, limit)
    return {"imports": [item.to_dict() for item in items], "count": len(items)}


@router.get("/source-quality")
def source_quality(limit: int = Query(100, ge=0, le=500)) -> dict[str, Any]:
    items = get_import_registry().list_source_quality(limit)
    return {"source_quality": [item.to_dict() for item in items], "count": len(items)}


@router.get("/source-quality/{source_name}")
def source_quality_detail(source_name: str) -> dict[str, Any]:
    item = get_import_registry().get_source_quality(source_name)
    return {"status": "not_found", "source_name": source_name} if item is None else {"source_quality": item.to_dict()}


@router.post("/market-discovery")
def market_discovery(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    try:
        paths = payload.get("dataset_paths") or []
        if not isinstance(paths, list) or len(paths) > 10:
            return {"status": "blocked", "blocked_reasons": ["dataset_path_limit_exceeded"]}
        max_categories = min(max(int(payload.get("max_categories", 10)), 0), 50)
        max_hypotheses = min(max(int(payload.get("max_hypotheses", 20)), 0), 100)
        return run_market_discovery(
            workspace_id=str(payload.get("workspace_id", "default")),
            title=str(payload.get("title", "Autonomous Market Discovery")),
            objective=str(payload.get("objective", "Find promising product categories and product hypotheses")),
            dataset_paths=[str(item) for item in paths],
            source_names=payload.get("source_names"),
            max_categories=max_categories,
            max_hypotheses=max_hypotheses,
            run_validation_services=bool(payload.get("run_validation_services", True)),
        )
    except Exception as exc:
        return {"status": "error", "error": "market_discovery_failed", "error_type": type(exc).__name__}


@router.get("/evidence")
def evidence(source_name: str | None = Query(None), source_type: str | None = Query(None), entity_type: str | None = Query(None), signal_type: str | None = Query(None), entity_name: str | None = Query(None), workspace_id: str | None = Query(None), limit: int = Query(100, ge=0, le=1000)) -> dict[str, Any]:
    try:
        items = get_discovery_registry().list_evidence(source_name, entity_type, signal_type, limit, source_type, entity_name, workspace_id)
        return {"evidence": [item.to_dict() for item in items], "count": len(items)}
    except Exception as exc:
        return {"status": "error", "error": "evidence_listing_failed", "error_type": type(exc).__name__, "evidence": []}


@router.get("/categories")
def categories(workspace_id: str | None = Query(None), status: str | None = Query(None), limit: int = Query(50, ge=0, le=500)) -> dict[str, Any]:
    items = get_discovery_registry().list_category_discoveries(workspace_id, status, limit)
    return {"discoveries": [item.to_dict() for item in items], "count": len(items)}


@router.get("/categories/{discovery_id}")
def category(discovery_id: str) -> dict[str, Any]:
    item = get_discovery_registry().get_category_discovery(discovery_id)
    return {"status": "not_found", "discovery_id": discovery_id} if item is None else {"discovery": item.to_dict()}


@router.get("/hypotheses")
def hypotheses(workspace_id: str | None = Query(None), discovery_id: str | None = Query(None), limit: int = Query(50, ge=0, le=500)) -> dict[str, Any]:
    items = get_discovery_registry().list_product_hypothesis_runs(workspace_id, discovery_id, limit)
    return {"hypothesis_runs": [item.to_dict() for item in items], "count": len(items)}


@router.get("/hypotheses/{hypothesis_run_id}")
def hypothesis(hypothesis_run_id: str) -> dict[str, Any]:
    item = get_discovery_registry().get_product_hypothesis_run(hypothesis_run_id)
    return {"status": "not_found", "hypothesis_run_id": hypothesis_run_id} if item is None else {"hypotheses": item.to_dict()}

@router.post("/opportunity-pipeline/refresh")
def refresh_pipeline(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    try:
        return refresh_opportunity_pipeline(str(payload.get("workspace_id", "default")), payload.get("discovery_id"), payload.get("hypothesis_run_id"))
    except Exception as exc:
        return {"status": "error", "error": "opportunity_pipeline_refresh_failed", "error_type": type(exc).__name__}

@router.get("/opportunities")
def opportunities(workspace_id: str | None = Query(None), stage: str | None = Query(None), opportunity_type: str | None = Query(None), recommendation: str | None = Query(None), limit: int = Query(100, ge=0, le=1000)) -> dict[str, Any]:
    items = get_opportunity_registry().list_opportunities(workspace_id, stage, opportunity_type, recommendation, limit)
    return {"opportunities": [x.to_dict() for x in items], "count": len(items)}

@router.get("/opportunities/{opportunity_id}")
def opportunity(opportunity_id: str) -> dict[str, Any]:
    item = get_opportunity_registry().get_opportunity(opportunity_id)
    return {"status": "not_found", "opportunity_id": opportunity_id} if item is None else {"opportunity": item.to_dict()}

@router.post("/opportunities/{opportunity_id}/evaluate-gates")
def opportunity_gates(opportunity_id: str) -> dict[str, Any]:
    item = get_opportunity_registry().get_opportunity(opportunity_id)
    if item is None: return {"status": "not_found", "opportunity_id": opportunity_id}
    from backend.discovery.discovery_registry import get_discovery_registry
    from backend.discovery.refinement_registry import get_refinement_registry
    from backend.discovery.calibration_registry import get_calibration_registry
    gaps = [g for a in get_refinement_registry().list_gap_analyses(item.workspace_id, 500) for g in a.gaps]
    return {"status": "completed", "gates": evaluate_opportunity_gates(item, get_discovery_registry().list_evidence(workspace_id=item.workspace_id, limit=10000), [], gaps, get_calibration_registry().list_profiles(item.workspace_id, limit=500))}

@router.post("/opportunities/{opportunity_id}/transition")
def transition_opportunity(opportunity_id: str, payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    registry = get_opportunity_registry(); item = registry.get_opportunity(opportunity_id); target = str(payload.get("to_stage", "")); reason = str(payload.get("reason", "")).strip()
    if item is None: return {"status": "not_found", "opportunity_id": opportunity_id}
    if target not in STAGES or target not in TRANSITIONS.get(item.stage, set()): return {"status": "blocked", "blocked_reasons": ["invalid_or_unauthorized_stage_transition"], "allowed_transitions": sorted(TRANSITIONS.get(item.stage, set()))}
    gates = opportunity_gates(opportunity_id).get("gates", {})
    if target == "launch_candidate" and gates.get("recommended_transition") != "launch_candidate": return {"status": "blocked", "blocked_reasons": ["launch_candidate_gate_not_passed"], "gates": gates}
    old = item.stage; item.stage = target; item.updated_at = __import__("time").time(); registry.update_opportunity(item)
    decision = "rejected" if target == "rejected" else "archived" if target == "archived" else "promoted"
    tr = OpportunityStageTransition("transition_" + __import__("uuid").uuid4().hex[:16], item.opportunity_id, item.workspace_id, old, target, decision, reason or "Manual gated transition.", gates, item.evidence_ids, item.report_ids); registry.register_transition(tr)
    return {"status": "updated", "opportunity": item.to_dict(), "transition": tr.to_dict(), "planning_only": target == "launch_candidate"}

@router.get("/opportunities/{opportunity_id}/transitions")
def opportunity_transitions(opportunity_id: str, limit: int = Query(100, ge=0, le=1000)) -> dict[str, Any]:
    items = get_opportunity_registry().list_transitions(opportunity_id=opportunity_id, limit=limit)
    return {"transitions": [x.to_dict() for x in items], "count": len(items)}

@router.get("/opportunity-pipeline/snapshots")
def pipeline_snapshots(workspace_id: str | None = Query(None), limit: int = Query(50, ge=0, le=500)) -> dict[str, Any]:
    items = get_opportunity_registry().list_snapshots(workspace_id, limit)
    return {"snapshots": [x.to_dict() for x in items], "count": len(items)}

@router.get("/opportunity-pipeline/snapshots/{snapshot_id}")
def pipeline_snapshot(snapshot_id: str) -> dict[str, Any]:
    item = get_opportunity_registry().get_snapshot(snapshot_id)
    return {"status": "not_found", "snapshot_id": snapshot_id} if item is None else {"snapshot": item.to_dict()}

@router.post("/validation-sprints")
def validation_sprints_create(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    try:
        limit=min(max(int(payload.get("limit",10)),0),25); ids=payload.get("opportunity_ids")
        if ids is not None and (not isinstance(ids,list) or len(ids)>25): return {"status":"blocked","blocked_reasons":["opportunity_id_limit_exceeded"]}
        return run_validation_sprint(str(payload.get("workspace_id","default")),ids,str(payload.get("title","Opportunity Validation Sprint")),str(payload.get("objective","Validate planning-ready opportunities with dry-run governed services")),limit,bool(payload.get("apply_transitions",True)))
    except Exception as exc: return {"status":"error","error":"validation_sprint_failed","error_type":type(exc).__name__}

@router.get("/validation-sprints")
def validation_sprints(workspace_id: str|None=Query(None), status: str|None=Query(None), limit: int=Query(50,ge=0,le=500)) -> dict[str,Any]:
    items=get_validation_sprint_registry().list_sprints(workspace_id,status,limit); return {"sprints":[x.to_dict() for x in items],"count":len(items)}

@router.get("/validation-sprints/{sprint_id}")
def validation_sprint(sprint_id: str) -> dict[str,Any]:
    x=get_validation_sprint_registry().get_sprint(sprint_id); return {"status":"not_found","sprint_id":sprint_id} if x is None else {"sprint":x.to_dict()}

@router.get("/validation-scorecards")
def validation_scorecards(workspace_id: str|None=Query(None), opportunity_id: str|None=Query(None), recommendation: str|None=Query(None), limit: int=Query(100,ge=0,le=1000)) -> dict[str,Any]:
    items=get_validation_sprint_registry().list_scorecards(workspace_id,opportunity_id,recommendation,limit); return {"scorecards":[x.to_dict() for x in items],"count":len(items)}

@router.get("/validation-scorecards/{scorecard_id}")
def validation_scorecard(scorecard_id: str) -> dict[str,Any]:
    x=get_validation_sprint_registry().get_scorecard(scorecard_id); return {"status":"not_found","scorecard_id":scorecard_id} if x is None else {"scorecard":x.to_dict()}

@router.post("/opportunities/{opportunity_id}/validation-sprint")
def opportunity_validation_sprint(opportunity_id: str, payload: dict[str,Any]=Body(default_factory=dict)) -> dict[str,Any]:
    from backend.discovery.opportunity_registry import get_opportunity_registry
    if get_opportunity_registry().get_opportunity(opportunity_id) is None: return {"status":"not_found","opportunity_id":opportunity_id}
    return run_validation_sprint(str(payload.get("workspace_id","default")),[opportunity_id],apply_transitions=bool(payload.get("apply_transitions",True)))
