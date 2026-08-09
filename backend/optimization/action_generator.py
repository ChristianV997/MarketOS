from __future__ import annotations

import uuid
from typing import Any

from .portfolio_actions import PortfolioAction, PortfolioActionSet
from .optimization_registry import get_optimization_registry


def _action_id(workspace: str, kind: str, key: str) -> str:
    return "action_" + uuid.uuid5(uuid.NAMESPACE_URL, f"{workspace}:{kind}:{key}").hex[:16]


def _safe_action(workspace, kind, title, description, *, opps=None, gaps=None, plans=None, cost=0, hours=1, info=0, confidence=0, risk=0, urgency=0, leverage=0, endpoint="", payload=None, blocked=None, required=None, rationale=None, metadata=None):
    score = max(0.0, min(100.0, info * .35 + confidence * .2 + risk * .15 + urgency * .15 + leverage * .15))
    return PortfolioAction(_action_id(workspace, kind, title), workspace, kind, title, description, opps or [], gaps or [], plans or [], safe_endpoint=endpoint, safe_payload=payload or {}, estimated_cost=cost, estimated_hours=hours, expected_information_gain=info, expected_confidence_delta=confidence, expected_risk_reduction=risk, expected_portfolio_value_delta=0, feasibility_score=100 if not blocked else 0, risk_score=10, urgency_score=urgency, leverage_score=leverage, confidence_score=confidence, total_action_score=score, blocked_reasons=blocked or [], required_inputs=required or [], status="blocked" if blocked else "candidate", rationale=rationale or ["This is a deterministic planning recommendation based on persisted MarketOS state."], metadata={"simulated_only": True, **(metadata or {})})


def generate_portfolio_actions(workspace_id: str = "default", max_actions: int = 100) -> PortfolioActionSet:
    max_actions = max(0, min(int(max_actions), 200)); blocked = []; actions = []
    try:
        from backend.discovery.opportunity_registry import get_opportunity_registry
        opportunities = get_opportunity_registry().list_opportunities(workspace_id=workspace_id, limit=200)
    except Exception: opportunities = []
    try:
        from backend.discovery.refinement_registry import get_refinement_registry
        refinement = get_refinement_registry(); analyses = refinement.list_gap_analyses(workspace_id, 20); plans = refinement.list_import_plans(workspace_id, 20)
    except Exception: analyses, plans = [], []
    gaps = analyses[0].gaps if analyses else []
    acquisition = []
    try:
        from backend.discovery.acquisition_registry import get_acquisition_registry
        acquisition = get_acquisition_registry().list_plans(workspace_id, limit=100)
    except Exception: pass
    if gaps:
        for gap in sorted(gaps, key=lambda x: (-x.priority_score, x.entity_name))[:max_actions]:
            matching = [x for x in acquisition if x.parser_type in gap.recommended_parser_types]
            actions.append(_safe_action(workspace_id, "acquire_evidence", f"Acquire {gap.missing_signal_type} evidence for {gap.entity_name}", "Request a documented local/cache export using the linked acquisition plan.", gaps=[gap.gap_id], plans=[x.plan_id for x in matching], cost=0, hours=1.0 + len(gap.required_fields) / 10, info=gap.priority_score, confidence=60, urgency=gap.priority_score, leverage=50, endpoint="/api/discovery/import-evidence" if matching else "", payload={"workspace_id": workspace_id, "parser_type": matching[0].parser_type if matching else (gap.recommended_parser_types[0] if gap.recommended_parser_types else "generic_market_csv"), "dry_run": True, "manual_export_only": True}, blocked=None if matching else ["acquisition_plan_missing"], required=["authorized local export", *gap.required_fields], rationale=gap.rationale + ["No demand, profitability, or market-size claim is made."]))
    else:
        actions.append(_safe_action(workspace_id, "run_refinement_cycle", "Run an initial evidence refinement cycle", "Create initial gap analysis, import recommendations, and safe templates.", cost=0, hours=0.5, info=70, confidence=35, urgency=80, leverage=60, endpoint="/api/discovery/refinement-cycle", payload={"workspace_id": workspace_id, "create_templates": True, "dry_run": True}, rationale=["No persisted gap analysis was available; setup work is required before portfolio claims."]))
    validation_ready = [x for x in opportunities if x.stage == "validation_ready"]
    if validation_ready:
        actions.append(_safe_action(workspace_id, "run_validation_sprint", "Run a dry-run validation sprint", "Evaluate validation-ready opportunities through governed read-only services.", opps=[x.opportunity_id for x in validation_ready[:25]], cost=0, hours=max(1.0, len(validation_ready) * .5), info=75, confidence=70, urgency=95, leverage=min(100, len(validation_ready) * 20), endpoint="/api/discovery/validation-sprints", payload={"workspace_id": workspace_id, "opportunity_ids":[x.opportunity_id for x in validation_ready[:25]], "apply_transitions": True, "dry_run": True}))
    if opportunities:
        actions.append(_safe_action(workspace_id, "refresh_pipeline", "Refresh the opportunity pipeline", "Re-evaluate stages after persisted evidence and refinement outputs change.", opps=[x.opportunity_id for x in opportunities], cost=0, hours=.25, info=45, confidence=35, urgency=75, leverage=min(100, len(opportunities) * 10), endpoint="/api/discovery/opportunity-pipeline/refresh", payload={"workspace_id": workspace_id, "dry_run": True}))
    comparisons = []
    try: comparisons = get_refinement_registry().list_comparisons(workspace_id, 20)
    except Exception: pass
    try:
        from backend.discovery.calibration_registry import get_calibration_registry
        profiles = get_calibration_registry().list_profiles(workspace_id, limit=100); calibration_runs = get_calibration_registry().list_calibration_runs(workspace_id, 20)
    except Exception: profiles, calibration_runs = [], []
    if comparisons and not calibration_runs:
        actions.append(_safe_action(workspace_id, "run_source_calibration", "Calibrate source usefulness", "Compare recorded imports and discovery changes using cautious non-causal signals.", cost=0, hours=.5, info=55, confidence=50, urgency=60, leverage=70, endpoint="/api/discovery/source-calibration", payload={"workspace_id": workspace_id, "dry_run": True}))
    try:
        from backend.discovery.validation_sprint_registry import get_validation_sprint_registry
        sprints = get_validation_sprint_registry().list_sprints(workspace_id, status="completed", limit=20)
        from backend.deliverables.registry import get_deliverable_registry
        has_package = bool(get_deliverable_registry().list_packages(workspace_id, package_type="product_validation_sprint", limit=1))
        if sprints and not has_package: actions.append(_safe_action(workspace_id, "generate_deliverable", "Generate a validation sprint deliverable", "Render a client-ready evidence-constrained Markdown/HTML package from the completed sprint.", hours=1, info=35, confidence=65, urgency=80, leverage=70, endpoint="/api/deliverables/product-validation-sprint", payload={"workspace_id": workspace_id, "include_appendices": True, "dry_run": True}))
    except Exception: pass
    if opportunities:
        actions.append(_safe_action(workspace_id, "run_refinement_cycle", "Refresh research refinement", "Recompute evidence gaps and next imports for the current opportunity portfolio.", opps=[x.opportunity_id for x in opportunities], hours=0.5, info=65, confidence=45, urgency=65, leverage=min(100, len(opportunities) * 15), endpoint="/api/discovery/refinement-cycle", payload={"workspace_id": workspace_id, "create_templates": True, "dry_run": True}))
    unique = {x.action_id: x for x in actions}; actions = sorted(unique.values(), key=lambda x: (-x.total_action_score, x.title))[:max_actions]; blocked = [x for x in unique.values() if x.status == "blocked"]
    result = PortfolioActionSet("action_set_" + uuid.uuid5(uuid.NAMESPACE_URL, f"{workspace_id}:{','.join(x.action_id for x in actions)}").hex[:16], workspace_id, "Portfolio Action Candidates", "Choose the next highest-value safe research actions under simulated constraints.", actions, sorted(blocked, key=lambda x: x.title), metadata={"simulated_only": True, "source_counts": {"opportunities": len(opportunities), "gaps": len(gaps), "comparisons": len(comparisons), "calibration_profiles": len(profiles)}})
    get_optimization_registry().register_action_set(result); return result
