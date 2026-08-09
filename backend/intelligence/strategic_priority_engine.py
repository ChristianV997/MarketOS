from __future__ import annotations
import uuid
from .strategic_priority import StrategicPriority,StrategicPriorityPlan
from .knowledge_graph_builder import build_knowledge_graph_snapshot
from .knowledge_registry import get_knowledge_registry
def build_strategic_priority_plan(workspace_id="default",max_priorities=20):
 from backend.discovery.opportunity_registry import get_opportunity_registry
 from backend.discovery.refinement_registry import get_refinement_registry
 from backend.discovery.acquisition_registry import get_acquisition_registry
 from backend.deliverables.registry import get_deliverable_registry
 opp=get_opportunity_registry().list_opportunities(workspace_id,limit=500); gaps=[g for a in get_refinement_registry().list_gap_analyses(workspace_id,50) for g in a.gaps]; plans=get_acquisition_registry().list_plans(workspace_id,limit=100); priorities=[]
 for gap in sorted(gaps,key=lambda x:(-x.priority_score,x.entity_name))[:max_priorities]:
  score=min(100,50+gap.priority_score*.45+(15 if plans else 0));priorities.append(StrategicPriority("priority_"+uuid.uuid5(uuid.NAMESPACE_URL,f"{workspace_id}:gap:{gap.gap_id}").hex[:16],workspace_id,"evidence_acquisition",f"Acquire evidence for {gap.entity_name}",f"Close the recorded {gap.missing_signal_type} gap.",gap.priority_score,75,60,gap.priority_score,35,25,score,[],[],[gap.gap_id],[],"Use the linked manual/cache import plan.","/api/discovery/refinement-cycle",{"workspace_id":workspace_id,"create_templates":True},"open",["A persisted high-priority evidence gap exists.","This can reduce uncertainty without live calls."],metadata={"dry_run":True}))
 for x in opp:
  if x.stage=="validation_ready":priorities.append(StrategicPriority("priority_"+uuid.uuid5(uuid.NAMESPACE_URL,f"{workspace_id}:opp:{x.opportunity_id}").hex[:16],workspace_id,"opportunity_validation",f"Validate {x.name}","Run the governed dry-run validation sprint.",70,x.score,x.confidence*100,70,45,20,75,[],[x.opportunity_id],x.gap_ids,x.report_ids,"Run a bounded validation sprint.","/api/discovery/validation-sprints",{"workspace_id":workspace_id,"opportunity_ids":[x.opportunity_id],"apply_transitions":True},"open",["Opportunity is validation-ready.","No external action is implied."],metadata={"dry_run":True}))
 if not priorities:priorities.append(StrategicPriority("priority_"+uuid.uuid4().hex[:16],workspace_id,"refinement_cycle","Establish the evidence baseline","Run discovery and refinement using approved local evidence.",80,80,25,90,40,10,80,[],[],[],[],"Run the initial safe discovery cycle.","/api/discovery/market-discovery",{"workspace_id":workspace_id,"run_validation_services":False},"open",["No strategic state is yet sufficient for prioritization."],metadata={"dry_run":True}))
 priorities=sorted(priorities,key=lambda x:(-x.total_priority_score,x.title))[:max(0,min(int(max_priorities),50))]
 optimization = None
 try:
  from backend.optimization.optimization_registry import get_optimization_registry
  optimization = get_optimization_registry().latest_plan(workspace_id)
 except Exception:
  optimization = None
 metadata={"dry_run_only":True}
 if optimization:
  metadata["optimization_plan_id"] = optimization.optimization_id
  metadata["optimization_summary"] = optimization.summary
  metadata["recommended_simulated_actions"] = [x.title for x in optimization.recommended_actions[:10]]
  priorities.extend([StrategicPriority("priority_"+uuid.uuid5(uuid.NAMESPACE_URL,f"{workspace_id}:optimization:{x.action_id}").hex[:16],workspace_id,"portfolio_optimization",f"Simulate: {x.title}",x.description, x.urgency_score,x.leverage_score,x.confidence_score,x.expected_information_gain,max(1,x.estimated_hours),x.risk_score,x.total_action_score,[],x.related_opportunity_ids,x.related_gap_ids,[],"Follow the safe endpoint only as a simulated/manual action.",x.safe_endpoint,x.safe_payload,"open",x.rationale,metadata={"dry_run_only":True,"optimization_action_id":x.action_id}) for x in optimization.recommended_actions[:max(0,min(int(max_priorities),10))]])
 priorities=sorted(priorities,key=lambda x:(-x.total_priority_score,x.title))[:max(0,min(int(max_priorities),50))]
 plan=StrategicPriorityPlan("priority_plan_"+uuid.uuid4().hex[:16],workspace_id,"Strategic Priority Plan","Reduce uncertainty and advance the highest-value research work.",priorities,{"opportunity_count":len(opp),"gap_count":len(gaps),"optimization_plan_id":optimization.optimization_id if optimization else ""},sorted({r for x in opp for r in x.risk_flags})[:10],sorted({g.missing_signal_type for g in gaps})[:10],[x.priority_id for x in priorities],metadata=metadata);return plan
