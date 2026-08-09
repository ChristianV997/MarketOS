from __future__ import annotations
import time, uuid
from .category_discovery import CategoryOpportunity
from .opportunity_pipeline import Opportunity, OpportunityPipelineSnapshot, OpportunityStageTransition, stable_opportunity_id
from .opportunity_registry import get_opportunity_registry
from .discovery_registry import get_discovery_registry
from .evidence_gap import analyze_evidence_gaps
from .refinement_registry import get_refinement_registry
from .acquisition_registry import get_acquisition_registry
from .calibration_registry import get_calibration_registry
from .opportunity_gates import evaluate_opportunity_gates
from backend.organization.report_registry import get_report_registry

def _match(value, names): return str(value or "").strip().lower() in {str(x or "").strip().lower() for x in names}
def build_opportunities_from_discovery(workspace_id="default", discovery_id=None, hypothesis_run_id=None, include_existing=True):
    dr=get_discovery_registry(); discovery=dr.get_category_discovery(discovery_id) if discovery_id else (dr.list_category_discoveries(workspace_id,limit=1) or [None])[0]; hyp=dr.get_product_hypothesis_run(hypothesis_run_id) if hypothesis_run_id else (dr.list_product_hypothesis_runs(workspace_id, discovery.discovery_id if discovery else None,1) or [None])[0]
    gaps=[]; rr=get_refinement_registry()
    for analysis in rr.list_gap_analyses(workspace_id,500): gaps.extend(analysis.gaps)
    plans=get_acquisition_registry().list_plans(workspace_id,limit=500); profiles=get_calibration_registry().list_profiles(workspace_id,limit=500); reports=get_report_registry().list_reports(workspace_id,limit=500); registry=get_opportunity_registry(); result=[]
    if discovery:
        for item in discovery.category_opportunities:
            oid=stable_opportunity_id(workspace_id,"category",item.category_name,discovery.discovery_id); old=registry.get_opportunity(oid) if include_existing else None; related_gaps=[g for g in gaps if _match(g.entity_name,[item.category_name]) or _match(g.category_name,[item.category_name])]; related_plans=[p for p in plans if set(p.related_gap_ids)&{g.gap_id for g in related_gaps}]; related_profiles=[p for p in profiles if p.source_name in discovery.source_names]; related_reports=[r for r in reports if item.category_name.lower() in (str(r.title)+" "+str(r.summary)).lower()]
            result.append(Opportunity(oid,workspace_id,"category",item.category_name,item.category_name,old.stage if old else "discovered",item.recommendation,item.score,item.score/100,item.evidence_ids,[r.report_id for r in related_reports],[g.gap_id for g in related_gaps],[p.plan_id for p in related_plans],[p.profile_id for p in related_profiles],discovery.discovery_id,"","",item.risk_flags,item.missing_evidence,["Import the highest-priority missing evidence."],old.created_at if old else time.time(),time.time(),{"synthetic_only":item.metadata.get("synthetic_or_cached_only",False)}))
    if hyp:
        for item in hyp.hypotheses:
            oid=stable_opportunity_id(workspace_id,"product_hypothesis",item.product_name,hyp.hypothesis_run_id); old=registry.get_opportunity(oid) if include_existing else None; related_gaps=[g for g in gaps if _match(g.entity_name,[item.product_name,item.category_name]) or _match(g.category_name,[item.category_name])]; related_plans=[p for p in plans if set(p.related_gap_ids)&{g.gap_id for g in related_gaps}]; related_profiles=[p for p in profiles if p.source_name in (discovery.source_names if discovery else [])]
            result.append(Opportunity(oid,workspace_id,"product_hypothesis",item.product_name,item.category_name,old.stage if old else "discovered",("investigate" if item.confidence>=.4 else "hold"),item.confidence*100,item.confidence,item.evidence_ids,[],[g.gap_id for g in related_gaps],[p.plan_id for p in related_plans],[p.profile_id for p in related_profiles],hyp.discovery_id,hyp.hypothesis_run_id,item.hypothesis_id,item.risk_flags,item.missing_evidence,["Validate supplier, price, competition, and demand evidence."],old.created_at if old else time.time(),time.time(),{"synthetic_only":item.metadata.get("synthetic_or_cached_only",False)}))
    return result
def refresh_opportunity_pipeline(workspace_id="default", discovery_id=None, hypothesis_run_id=None):
    registry=get_opportunity_registry(); items=build_opportunities_from_discovery(workspace_id,discovery_id,hypothesis_run_id); records=get_discovery_registry().list_evidence(workspace_id=workspace_id,limit=10000); gaps=[]
    for x in get_refinement_registry().list_gap_analyses(workspace_id,500): gaps.extend(x.gaps)
    reports=get_report_registry().list_reports(workspace_id,limit=500); profiles=get_calibration_registry().list_profiles(workspace_id,limit=500); transitions=[]
    for item in items:
        gate=evaluate_opportunity_gates(item,records,reports,gaps,profiles); target=gate.get("recommended_transition"); item.metadata["last_gate_results"]=gate; item.next_actions=gate.get("required_next_evidence") or item.next_actions
        if target and target in __import__("backend.discovery.opportunity_pipeline",fromlist=["TRANSITIONS"]).TRANSITIONS.get(item.stage,set()):
            previous=item.stage; item.stage=target; item.updated_at=time.time(); decision="rejected" if target=="rejected" else "promoted"; tr=OpportunityStageTransition("transition_"+uuid.uuid4().hex[:16],item.opportunity_id,workspace_id,previous,target,decision,"Deterministic evidence gate evaluation.",gate,item.evidence_ids,item.report_ids); registry.register_transition(tr); transitions.append(tr)
        registry.register_opportunity(item)
    counts={stage:sum(x.stage==stage for x in items) for stage in __import__("backend.discovery.opportunity_pipeline",fromlist=["STAGES"]).STAGES}; top=[{"opportunity_id":x.opportunity_id,"name":x.name,"stage":x.stage,"score":x.score,"confidence":x.confidence} for x in sorted(items,key=lambda x:(-x.score,x.name))[:10]]; blocked=[x for x in top if x["stage"] not in {"validation_ready","launch_candidate","rejected","archived"}]; rejected=[x for x in top if x["stage"]=="rejected"]; actions=[]
    for x in items:
        for action in x.next_actions:
            if action not in actions: actions.append(action)
    snapshot=OpportunityPipelineSnapshot("snapshot_"+uuid.uuid4().hex[:16],workspace_id,"Opportunity Pipeline Snapshot",items,counts,top,blocked,rejected,actions[:20],metadata={"planning_only":True}); registry.register_snapshot(snapshot)
    try:
        from backend.obsidian.sync import sync_opportunity_pipeline_snapshot_note, sync_opportunity_note
        obsidian={"snapshot":sync_opportunity_pipeline_snapshot_note(snapshot),"opportunities":[sync_opportunity_note(x,registry.list_transitions(opportunity_id=x.opportunity_id)) for x in items]}
    except Exception as exc: obsidian={"status":"warning","error":type(exc).__name__}
    return {"opportunities":[x.to_dict() for x in items],"transitions":[x.to_dict() for x in transitions],"snapshot":snapshot.to_dict(),"snapshot_id":snapshot.snapshot_id,"obsidian":obsidian,"status":"completed"}
