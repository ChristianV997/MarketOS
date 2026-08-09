from __future__ import annotations
import time,uuid
from .opportunity_registry import get_opportunity_registry
from .opportunity_pipeline import OpportunityStageTransition
from .validation_sprint import ValidationSprint,ValidationSprintTarget,ValidationServiceResult,stable_sprint_id
from .validation_service_plan import build_validation_service_plan,build_service_inputs_for_opportunity
from .validation_scorecard import build_validation_scorecard
from .validation_sprint_registry import get_validation_sprint_registry
from .discovery_registry import get_discovery_registry
from backend.organization.planner_executor_reviewer import run_planner_executor_reviewer
from backend.organization.report_registry import get_report_registry

def select_validation_targets(workspace_id="default",opportunity_ids=None,limit=10):
    registry=get_opportunity_registry(); items=[]
    if opportunity_ids:
        items=[registry.get_opportunity(x) for x in opportunity_ids]; items=[x for x in items if x and x.workspace_id==workspace_id and x.stage not in {"rejected","archived"}]
    else: items=registry.list_opportunities(workspace_id,stage="validation_ready",limit=1000)
    return [ValidationSprintTarget("target_"+uuid.uuid5(uuid.NAMESPACE_URL,x.opportunity_id).hex[:16],x.opportunity_id,x.opportunity_type,x.name,x.category_name,x.stage,build_validation_service_plan(x),x.evidence_ids,x.report_ids,{"workspace_id":workspace_id}) for x in sorted(items,key=lambda x:(-x.score,x.name))[:max(0,min(int(limit),25))]]

def run_validation_sprint(workspace_id="default",opportunity_ids=None,title="Opportunity Validation Sprint",objective="Validate planning-ready opportunities with dry-run governed services",limit=10,apply_transitions=True):
    targets=select_validation_targets(workspace_id,opportunity_ids,limit); registry=get_validation_sprint_registry(); sprint=ValidationSprint(stable_sprint_id(workspace_id,title),workspace_id,title,objective,"running",targets,metadata={"planning_only":True}); registry.register_sprint(sprint)
    if not targets:
        sprint.status="blocked"; sprint.blocked_reasons=["no_validation_targets"]; sprint.finished_at=time.time(); registry.update_sprint(sprint); return {"sprint":sprint.to_dict(),"scorecards":[],"transitions":[],"status":"blocked"}
    transitions=[]; reports=[]
    for target in targets:
        opportunity=get_opportunity_registry().get_opportunity(target.opportunity_id); results=[]
        for service in target.service_plan:
            inputs=build_service_inputs_for_opportunity(opportunity,service,get_discovery_registry().list_evidence(workspace_id=workspace_id,limit=10000))
            if inputs.get("_missing_inputs"):
                results.append(ValidationServiceResult("result_"+uuid.uuid4().hex[:16],target.opportunity_id,service,"skipped",missing_evidence=inputs["_missing_inputs"],blocked_reasons=["missing_safe_inputs"])); continue
            try:
                outcome=run_planner_executor_reviewer(f"Validation sprint: {opportunity.name}",workspace_id,"product" if service=="product_research" else "growth" if service=="customer_intelligence" else "finance",service,inputs)
                execution=outcome.get("execution",{}); status="completed" if execution.get("status")=="completed" else "unavailable" if execution.get("status")=="service_module_unavailable" else "blocked"; report_id=outcome.get("report_id","");
                if report_id: reports.append(report_id)
                results.append(ValidationServiceResult("result_"+uuid.uuid4().hex[:16],target.opportunity_id,service,status,report_id,10 if status=="completed" else -5,execution.get("output",{}).get("findings",[]) if isinstance(execution.get("output"),dict) else [],execution.get("output",{}).get("next_actions",[]) if isinstance(execution.get("output"),dict) else [],execution.get("output",{}).get("risk_flags",[]) if isinstance(execution.get("output"),dict) else [],execution.get("output",{}).get("missing_evidence",[]) if isinstance(execution.get("output"),dict) else [],execution.get("blocked_reasons",[]) or execution.get("errors",[])))
            except Exception as exc: results.append(ValidationServiceResult("result_"+uuid.uuid4().hex[:16],target.opportunity_id,service,"failed",blocked_reasons=[type(exc).__name__]))
        scorecard=build_validation_scorecard(opportunity,results,get_discovery_registry().list_evidence(workspace_id=workspace_id,limit=10000)); scorecard.metadata["workspace_id"]=workspace_id; registry.register_scorecard(scorecard); sprint.scorecards.append(scorecard); opportunity.report_ids=sorted(set(opportunity.report_ids+[x.report_id for x in results if x.report_id])); opportunity.metadata["latest_validation_scorecard_id"]=scorecard.scorecard_id; get_opportunity_registry().update_opportunity(opportunity)
        if apply_transitions and scorecard.transition_recommendation in {"launch_candidate","rejected"} and scorecard.transition_recommendation in __import__("backend.discovery.opportunity_pipeline",fromlist=["TRANSITIONS"]).TRANSITIONS.get(opportunity.stage,set()):
            old=opportunity.stage; opportunity.stage=scorecard.transition_recommendation; get_opportunity_registry().update_opportunity(opportunity); tr=OpportunityStageTransition("transition_"+uuid.uuid4().hex[:16],opportunity.opportunity_id,workspace_id,old,opportunity.stage,"promoted" if opportunity.stage=="launch_candidate" else "rejected","Validation scorecard recommendation.",scorecard.to_dict(),opportunity.evidence_ids,opportunity.report_ids); get_opportunity_registry().register_transition(tr); transitions.append(tr)
    portfolio=None
    try:
        from backend.organization.portfolio_report import build_portfolio_report
        portfolio=build_portfolio_report(workspace_id,[get_report_registry().get(x) for x in reports if get_report_registry().get(x)],f"{title} portfolio"); get_report_registry().register_portfolio_report(portfolio); sprint.portfolio_report_id=portfolio.portfolio_report_id
    except Exception: pass
    sprint.report_ids=sorted(set(reports)); sprint.status="completed" if all(x.recommendation not in {"request_more_evidence"} for x in sprint.scorecards) else "partial"; sprint.finished_at=time.time(); registry.update_sprint(sprint)
    try:
        from backend.obsidian.sync import sync_validation_sprint_note, sync_validation_scorecard_note
        obsidian={"sprint":sync_validation_sprint_note(sprint),"scorecards":[sync_validation_scorecard_note(x) for x in sprint.scorecards]}
    except Exception as exc:
        obsidian={"status":"warning","error":type(exc).__name__}
    return {"sprint":sprint.to_dict(),"scorecards":[x.to_dict() for x in sprint.scorecards],"portfolio_report":portfolio.to_dict() if portfolio else None,"transitions":[x.to_dict() for x in transitions],"obsidian":obsidian,"status":sprint.status}
