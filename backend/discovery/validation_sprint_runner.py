from __future__ import annotations
import hashlib,json,math,time,uuid
from collections import Counter
from dataclasses import asdict,is_dataclass
from typing import Mapping
from .opportunity_registry import get_opportunity_registry
from .opportunity_pipeline import OpportunityStageTransition
from .validation_sprint import ValidationSprint,ValidationSprintTarget,ValidationServiceResult,PlannedValidationTarget,ValidationSprintPlan,stable_sprint_id
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

PLAN_OBJECTIVE="Plan a governed dry-run validation sprint; no service, registry, stage, or external action runs."
PLAN_CALLABLE="backend.discovery.validation_sprint_runner.run_validation_sprint"
DEEP_VALIDATION_ACTION="deep_validate_product"
SPRINT_RESOURCE="report_generation_quota"
EVIDENCE_PAGE_CAP=1000
OPPORTUNITY_PAGE_CAP=1000
_THRESHOLD_REASON="projected budget use exceeds the approval threshold; finance review required"
_LEARNING_EVENT_KEYS=frozenset({"learning_event_id","event_type","outcome","workspace_id","candidate_id","action_taken","failure_reasons","success_reasons","client_visibility","owner_department","hypothesis","provider_id","resource_governor_influence","metrics","cost_estimate","confidence"})
_PERMITTED_OUTCOMES=frozenset({"allow","queue"})
_BLOCKED_OUTCOMES=frozenset({"soft_block","hard_block"})
_APPROVAL_OUTCOMES=frozenset({"requires_approval","requires_finance_review","requires_management_review","requires_trustos_review","requires_workspace_review","requires_experiment_design","requires_learning_capture"})
_SIDE_EFFECTS_DISCLOSED=("service executor invocations","validation sprint registry write","opportunity registry write (scorecard reference and stage transitions)","Obsidian sync attempt")
_STEP_BY_REASON={"no_evidence_recorded":"record_evidence","unresolved_evidence_reference":"resolve_evidence_reference","evidence_reference_outside_loaded_pool":"reload_complete_evidence_pool","opportunity_not_found":"verify_opportunity_id","workspace_mismatch":"verify_workspace","duplicate_opportunity_records":"resolve_duplicate_records","no_permitted_services":"review_service_contracts","no_services_with_complete_inputs":"supply_service_inputs"}

def _digest(*parts): return hashlib.sha256(json.dumps(parts,sort_keys=True,default=str).encode("utf-8")).hexdigest()
def _unit(value):
    try: number=float(value)
    except (TypeError,ValueError): return 0.0
    return round(max(0.0,min(1.0,number)),4) if math.isfinite(number) else 0.0
def _sort_key(item): return (-float(item.score or 0.0),str(item.name),str(item.opportunity_id))
def _policy_fingerprint(value):
    if value is None: return None
    if is_dataclass(value): return asdict(value)
    return [asdict(x) for x in value]
def _candidate_fingerprint(items):
    return sorted((x.workspace_id,x.opportunity_type,x.name,x.category_name,x.stage,round(float(x.score or 0.0),6),sorted(str(e) for e in x.evidence_ids),json.dumps(x.metadata or {},sort_keys=True,default=str)) for x in items)

def plan_validation_sprint(candidates,*,workspace_id="default",requested_ids=None,title="Opportunity Validation Sprint",objective=PLAN_OBJECTIVE,limit=10,evidence_records=(),learning_context=None,acknowledged_learning_for=(),budgets=None,portfolio=None,runaway=None,warnings=())->ValidationSprintPlan:
    """Pure, deterministic sprint preflight over supplied opportunities.

    Reads no registry, writes no state, invokes no service, and transitions no stage. Governance runs in canonical
    (score, name, id) order regardless of input or request order, so the shared quota and budget fall on the same
    targets for permuted or repeated inputs. The limit is applied after that ordering and is reported, never silent.
    Fail-closed rules: conflicting records for one id, unresolved evidence references, absent evidence, unknown
    learning vocabulary, and learning history beyond the ledger's review bound each keep a target out of the plan.
    A learning constraint blocks only the candidate it was recorded for, until a human-reviewed caller lists that
    candidate in `acknowledged_learning_for`. A recurring TrustOS blocker is never released by acknowledgement.
    The plan_id digests the inputs and the full output.
    """
    from evaluation.companyos.learning_ledger import EVENT_TYPES,FAILURE_REASONS,OUTCOMES,SUCCESS_REASONS,build_learning_ledger_report,derive_governor_influence
    from evaluation.companyos.resource_execution_governor import ACTION_TYPES,ExecutionDecisionRequest,apply_learning_influence,evaluate_execution_request
    if learning_context is not None and not isinstance(learning_context,Mapping): raise ValueError("learning_context must be a mapping")
    if learning_context is not None and set(learning_context)-{"events"}: raise ValueError("learning_context accepts only 'events'")
    events=list((learning_context or {}).get("events",[]) or [])
    for event in events:
        if not isinstance(event,Mapping): raise ValueError("learning events must be mappings")
        for key in ("learning_event_id","event_type","outcome","workspace_id","candidate_id","action_taken"):
            if not str(event.get(key,"") or "").strip(): raise ValueError(f"learning events must name {key} so constraints cannot drop silently")
        if event["event_type"] not in EVENT_TYPES or event["outcome"] not in OUTCOMES: raise ValueError("learning events need a known event_type and outcome")
        unknown=set(event)-_LEARNING_EVENT_KEYS
        if unknown: raise ValueError("learning events contain unknown keys: "+",".join(sorted(unknown)))
        if event["action_taken"] not in ACTION_TYPES: raise ValueError("learning events must name a governor action in action_taken")
        if any(reason not in FAILURE_REASONS for reason in (event.get("failure_reasons") or [])): raise ValueError("learning events use an unknown failure reason")
        if any(reason not in SUCCESS_REASONS for reason in (event.get("success_reasons") or [])): raise ValueError("learning events use an unknown success reason")
    budgets=None if budgets is None else tuple(budgets)
    grouped={}
    for item in candidates:
        if item is not None: grouped.setdefault(str(item.opportunity_id),[]).append(item)
    acknowledged=frozenset(str(x) for x in acknowledged_learning_for)
    requested=None if requested_ids is None else sorted(dict.fromkeys(str(x) for x in requested_ids))
    def _group_key(oid): return min(_sort_key(x) for x in grouped[oid])
    found=sorted(grouped,key=_group_key) if requested is None else sorted((x for x in requested if x in grouped),key=_group_key)
    missing=[] if requested is None else [x for x in requested if x not in grouped]
    bounded=max(0,min(int(limit),25)); beyond=found[bounded:]; ids=found[:bounded]+missing
    extra_warnings=[f"validation_ready_beyond_limit:{len(beyond)}"] if beyond and requested is None else []
    warnings=sorted(set([*warnings,*extra_warnings]))
    learning_report=build_learning_ledger_report(context={"events":events})
    evidence=list(evidence_records or ())
    pool_complete="evidence_pool_may_be_truncated" not in set(warnings)
    evidence_by_id={}; evidence_conflicts=set()
    for record in evidence:
        key=str(getattr(record,"evidence_id",""))
        if key in evidence_by_id and evidence_by_id[key] is not record: evidence_conflicts.add(key)
        evidence_by_id.setdefault(key,record)
    policy=[_policy_fingerprint(budgets),_policy_fingerprint(portfolio),_policy_fingerprint(runaway)]
    inputs={"requested":requested,"limit":limit,"title":title,"objective":objective,"acknowledged":sorted(acknowledged),"evidence":sorted(evidence_by_id),"evidence_conflicts":sorted(evidence_conflicts),"learning":[json.dumps(e,sort_keys=True,default=str) for e in events],"candidates":[[oid,_candidate_fingerprint(grouped.get(oid,[]))] for oid in ids],"policy":policy,"warnings":warnings,"beyond":beyond}
    targets=[]; consumed_actions=0; consumed_amount=0.0; outcome_counts=Counter(); approvals=[]
    for oid in beyond if requested is not None else []:
        targets.append(PlannedValidationTarget("vsp_target_"+_digest("target",workspace_id,oid)[:16],oid,"","",False,"ineligible",reasons=["beyond_limit"]))
    for oid in ids:
        items=grouped.get(oid,[]); target_id="vsp_target_"+_digest("target",workspace_id,oid)[:16]
        if not items:
            targets.append(PlannedValidationTarget(target_id,oid,"","",False,"ineligible",reasons=["opportunity_not_found"])); continue
        if any(x is not items[0] for x in items[1:]):
            targets.append(PlannedValidationTarget(target_id,oid,"","",False,"ineligible",reasons=["duplicate_opportunity_records"])); continue
        opp=items[0]; reasons=[]; planned=[]; skipped={}; unsupported=[]
        if opp.workspace_id!=workspace_id:
            targets.append(PlannedValidationTarget(target_id,oid,"","",False,"ineligible",reasons=["workspace_mismatch"])); continue
        if opp.stage!="validation_ready": reasons.append(f"stage_not_validation_ready:{opp.stage}")
        if not opp.evidence_ids: reasons.append("no_evidence_recorded")
        conflicted=sorted(str(x) for x in opp.evidence_ids if str(x) in evidence_conflicts)
        if conflicted: reasons.append("duplicate_evidence_records:"+",".join(conflicted))
        unresolved=sorted(str(x) for x in opp.evidence_ids if str(x) not in evidence_by_id)
        if unresolved: reasons.append(("unresolved_evidence_reference:" if pool_complete else "evidence_reference_outside_loaded_pool:")+",".join(unresolved))
        services=build_validation_service_plan(opp)
        if not services: reasons.append("no_permitted_services")
        for service in services:
            service_inputs=build_service_inputs_for_opportunity(opp,service,evidence)
            if service_inputs.get("_unsupported"): unsupported.append(service); continue
            if service_inputs.get("_missing_inputs"): skipped[service]=sorted(service_inputs["_missing_inputs"]); continue
            planned.append(service)
        if services and not planned:
            reasons.extend(f"unsupported_service:{x}" for x in unsupported)
            if skipped or not unsupported: reasons.append("no_services_with_complete_inputs")
        if reasons:
            targets.append(PlannedValidationTarget(target_id,oid,opp.name,opp.stage,False,"ineligible",skipped_services=skipped,reasons=reasons)); continue
        influence=derive_governor_influence(learning_report,action_type=DEEP_VALIDATION_ACTION,candidate_id=oid,workspace_id=workspace_id,allow_action_type_fallback=False)
        learning_history=sum(1 for e in events if str(e.get("candidate_id"))==oid and str(e.get("action_taken"))==DEEP_VALIDATION_ACTION and str(e.get("workspace_id"))==workspace_id)
        request=ExecutionDecisionRequest(request_id=f"validation-sprint:{target_id}",action_type=DEEP_VALIDATION_ACTION,domain="intelligence",owner_department="intelligence",workspace_id=workspace_id,requested_amount=float(len(planned)),resource_type=SPRINT_RESOURCE,model_tier="algorithmic",evidence_score=_unit(opp.confidence),opportunity_score=_unit(float(opp.score or 0.0)/100.0),learning_captured=oid in acknowledged,workflow_steps=len(planned),child_tasks=len(planned))
        request=apply_learning_influence(request,influence.to_governor_context())
        prior_amount,prior_count=consumed_amount,consumed_actions
        decision=evaluate_execution_request(request,budgets=budgets,portfolio=portfolio,runaway=runaway,prior_plan_amount=prior_amount,prior_action_count=prior_count)
        outcome=decision.outcome
        governor_approvals=[{"approval_type":a.approval_type,"approver_role":a.approver_role,"reason":a.reason,"linked_action":a.linked_action} for a in decision.approvals]
        threshold=[b for b in decision.budget_checks if b.approval_required]
        approval_rows=governor_approvals
        if outcome in _PERMITTED_OUTCOMES and threshold and not governor_approvals:
            approval_rows=[{"approval_type":"budget_approval_threshold","approver_role":"finance_manager","reason":_THRESHOLD_REASON,"linked_action":DEEP_VALIDATION_ACTION}]
        hold=[]
        overlays=set()
        if influence.trustos_recurrence_blocked: hold.append("trustos_recurrence_requires_trustos_review"); overlays.add("trustos_hold")
        if learning_history>25: hold.append("learning_history_exceeds_review_bound"); overlays.add("learning_history_bound")
        if outcome in _PERMITTED_OUTCOMES and threshold and not governor_approvals: overlays.add("budget_approval_threshold")
        if outcome in _BLOCKED_OUTCOMES or outcome not in _PERMITTED_OUTCOMES|_APPROVAL_OUTCOMES: status="blocked"
        elif outcome in _APPROVAL_OUTCOMES or approval_rows: status="awaiting_approval"
        else: status="planned"
        if hold: status="blocked"
        outcome_counts[outcome]+=1
        if status!="blocked": consumed_actions+=1; consumed_amount+=float(len(planned))
        if status=="awaiting_approval":
            for row in approval_rows: approvals.append({"target_id":target_id,"opportunity_id":oid,**row})
        results=[]
        for service in services:
            rid="result_"+_digest("result",target_id,service)[:16]
            if service in skipped: results.append(ValidationServiceResult(rid,oid,service,"skipped",missing_evidence=skipped[service],blocked_reasons=["missing_safe_inputs"]))
            elif service in unsupported: results.append(ValidationServiceResult(rid,oid,service,"skipped",blocked_reasons=["unsupported_service"]))
            else: results.append(ValidationServiceResult(rid,oid,service,"skipped",blocked_reasons=(list(decision.blockers)+hold) if status=="blocked" else ["not_executed_in_plan"]))
        candidate_evidence=[evidence_by_id[str(x)] for x in opp.evidence_ids if str(x) in evidence_by_id]
        scorecard=build_validation_scorecard(opp,results,evidence_records=candidate_evidence,scorecard_id="scorecard_preview_"+_digest("scorecard",target_id)[:16])
        scorecard.failed_checks=[x for x in scorecard.failed_checks if not x.endswith("_skipped")]
        scorecard.metadata.update({"workspace_id":workspace_id,"preview":True,"registered":False,"preflight_only":True})
        preview_missing=list(scorecard.missing_evidence)
        gaps=[f"missing_evidence:{x}" for x in preview_missing]+[f"unsupported_service:{x}" for x in unsupported]
        if status=="planned" and gaps: status="partial"
        if status=="blocked": base=(list(decision.blockers)+hold) or [f"governor_outcome:{outcome}"]
        elif status=="awaiting_approval": base=[decision.reason] if governor_approvals else [_THRESHOLD_REASON]
        else: base=[]
        target_reasons=list(dict.fromkeys(base+gaps))
        scorecard.metadata["governor_status"]=status
        governor={"action_type":DEEP_VALIDATION_ACTION,"outcome":outcome,"reason":decision.reason,"blockers":list(decision.blockers),"approvals":governor_approvals,"budget_checks":[b.to_dict() for b in decision.budget_checks],"quota_checks":[q.to_dict() for q in decision.quota_checks],"requested_amount":float(len(planned)),"prior_plan_amount":prior_amount,"prior_action_count":prior_count,"simulated_only":decision.simulated_only,"plan_overlays":sorted(overlays)}
        learning={"candidate_scoped":True,"evidence_mode":influence.evidence_mode,"previous_learning_required":bool(request.previous_learning_required),"learning_acknowledged":oid in acknowledged,"learning_history_count":learning_history,"trustos_hold":bool(influence.trustos_recurrence_blocked),"do_not_repeat_rule_ids":list(influence.do_not_repeat_rule_ids),"kill_blocks_resumption":bool(influence.kill_blocks_resumption),"hold_or_avoid":bool(influence.hold_or_avoid),"rationale":list(influence.rationale)}
        targets.append(PlannedValidationTarget(target_id,oid,opp.name,opp.stage,True,status,planned,skipped,target_reasons,governor,learning,scorecard.to_dict()))
    governed=[t for t in targets if t.status in {"planned","partial","awaiting_approval"}]
    if not targets: plan_status,plan_reasons="blocked",["no_validation_targets"]
    elif not governed: plan_status,plan_reasons="blocked",sorted({r for t in targets for r in t.reasons})
    elif all(t.status=="planned" for t in targets): plan_status,plan_reasons="planned",[]
    else: plan_status,plan_reasons="partial",sorted({r for t in targets for r in t.reasons})
    steps=set()
    for t in targets:
        if t.status=="ineligible":
            for reason in t.reasons:
                key=reason.split(":")[0]
                step="advance_stage_via_review" if key=="stage_not_validation_ready" else "raise_limit_or_split_request" if key=="beyond_limit" else _STEP_BY_REASON.get(key,"resolve_"+key)
                steps.add(f"{step}:{t.opportunity_id}")
        for service,missing in sorted(t.skipped_services.items()): steps.add(f"supply_inputs:{service}:{','.join(missing)}:{t.opportunity_id}")
        covered={m for lst in t.skipped_services.values() for m in lst}
        if t.eligible:
            for item in t.scorecard_preview.get("missing_evidence",[]):
                if item not in covered: steps.add(f"supply_evidence:{item}:{t.opportunity_id}")
        for reason in t.reasons:
            if reason.startswith("evidence_reference_outside_loaded_pool:"): steps.add(f"reload_complete_evidence_pool:{t.opportunity_id}")
            if reason.startswith("unsupported_service:"): steps.add(f"review_service_contract:{reason.split(':',1)[1]}:{t.opportunity_id}")
            if reason=="trustos_recurrence_requires_trustos_review": steps.add(f"request_trustos_review:{t.opportunity_id}")
            if reason=="learning_history_exceeds_review_bound": steps.add(f"human_review_learning_history:{t.opportunity_id}")
        if t.status=="blocked":
            for blocker in t.governor.get("blockers",[]): steps.add(f"resolve_governor_blocker:{blocker.replace(' ','_')}:{t.opportunity_id}")
            if t.learning.get("previous_learning_required") and not t.learning.get("learning_acknowledged") and not t.learning.get("trustos_hold"): steps.add(f"review_prior_learning_then_acknowledge:{t.opportunity_id}")
    for row in approvals: steps.add(f"request_approval:{row['approver_role']}:{row['opportunity_id']}")
    ready=sorted(t.opportunity_id for t in targets if t.status in {"planned","partial"})
    if ready: steps.add("human_review_then_explicit_run_validation_sprint")
    handoff={"callable":PLAN_CALLABLE,"authorized":False,"requires_explicit_invocation":True,"requires_human_approval":bool(approvals),"payload":None if not ready else {"workspace_id":workspace_id,"opportunity_ids":ready,"title":title,"apply_transitions":False,"limit":len(ready)},"side_effects_disclosed":list(_SIDE_EFFECTS_DISCLOSED)}
    safety={"planning_only":True,"read_only":True,"execution_authorized":False,"service_executor_invocations":0,"registry_writes":0,"opportunity_stage_transitions":0,"obsidian_writes":0,"network_calls":False,"provider_calls":False,"external_mutations":False,"approval_authority":"CompanyOS Approval Ledger (not granted by this plan)","governor_authority":"evaluation.companyos.resource_execution_governor","learning_source":"caller-supplied fixture-backed events","scorecard_mode":"preview_unregistered","trustos_gate":"not_evaluated_by_plan","workspace_isolation_gate":"not_evaluated_by_plan","launch_authority":"none","run_binding":"not_bound_run_validation_sprint_does_not_read_this_plan"}
    summary={"action_type":DEEP_VALIDATION_ACTION,"resource_type":SPRINT_RESOURCE,"outcomes":dict(sorted(outcome_counts.items())),"consumed_actions":consumed_actions,"consumed_amount":round(consumed_amount,4)}
    body={"status":plan_status,"targets":[asdict(t) for t in targets],"reasons":plan_reasons,"governor_summary":summary,"approvals_required":approvals,"next_safe_steps":sorted(steps),"execution_handoff":handoff,"safety":safety,"warnings":warnings}
    plan_id="vsplan_"+_digest("plan",inputs,body)[:16]
    return ValidationSprintPlan(plan_id,workspace_id,title,objective,plan_status,targets,plan_reasons,summary,approvals,sorted(steps),handoff,safety,warnings)

def build_validation_sprint_plan(workspace_id="default",opportunity_ids=None,limit=10,*,title="Opportunity Validation Sprint",objective=PLAN_OBJECTIVE,learning_context=None,acknowledged_learning_for=(),budgets=None,portfolio=None,runaway=None)->ValidationSprintPlan:
    """Programmatic seam for planning from live registries. Reads only; never registers, saves, or executes.

    An explicit `opportunity_ids` list, including an empty one, is an exact selection; only `None` selects the
    validation-ready pool. Truncation of the pool or the evidence read is reported as a warning.
    """
    registry=get_opportunity_registry()
    warnings=[]
    requested=None
    if opportunity_ids is not None:
        requested=[str(x) for x in opportunity_ids]
        candidates=[x for x in (registry.get_opportunity(y) for y in dict.fromkeys(requested)) if x is not None and x.workspace_id==workspace_id]
    else:
        candidates=registry.list_opportunities(workspace_id,stage="validation_ready",limit=1000)
        if len(candidates)>=OPPORTUNITY_PAGE_CAP: warnings.append("opportunity_pool_may_be_truncated")
    evidence=get_discovery_registry().list_evidence(workspace_id=workspace_id,limit=10000)
    if len(evidence)>=EVIDENCE_PAGE_CAP: warnings.append("evidence_pool_may_be_truncated")
    return plan_validation_sprint(candidates,workspace_id=workspace_id,requested_ids=requested,title=title,objective=objective,limit=limit,evidence_records=evidence,learning_context=learning_context,acknowledged_learning_for=acknowledged_learning_for,budgets=budgets,portfolio=portfolio,runaway=runaway,warnings=warnings)

def run_validation_sprint(workspace_id="default",opportunity_ids=None,title="Opportunity Validation Sprint",objective="Validate planning-ready opportunities with dry-run governed services",limit=10,apply_transitions=True,*,authorized=False):
    """Execute a validation sprint only after an explicit execution authorization.

    The planning seam is advisory and must not accidentally become an execution
    path merely because a caller invokes this function with its default values.
    Unauthorized calls return a bounded non-mutating response before reading or
    writing any execution registry.
    """
    if authorized is not True:
        return {
            "status": "blocked",
            "sprint": None,
            "scorecards": [],
            "transitions": [],
            "portfolio_report": None,
            "obsidian": {"status": "not_run"},
            "blocked_reasons": ["execution_not_authorized"],
            "execution_authorized": False,
        }
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
