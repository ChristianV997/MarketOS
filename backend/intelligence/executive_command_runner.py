from .knowledge_graph_builder import build_knowledge_graph_snapshot
from .strategic_priority_engine import build_strategic_priority_plan
from .research_campaign_engine import build_research_campaign_plan
from .executive_brief_engine import build_executive_brief
def run_executive_intelligence_cycle(workspace_id="default",objective="Assess MarketOS strategic state and recommend next actions",build_graph=True,build_priorities=True,build_campaigns=True,build_brief=True):
 out={"warnings":[],"status":"completed"}
 try:out["knowledge_graph"]=build_knowledge_graph_snapshot(workspace_id) if build_graph else None
 except Exception as e:out["warnings"].append(f"knowledge_graph_failed:{type(e).__name__}")
 try:out["priority_plan"]=build_strategic_priority_plan(workspace_id).to_dict() if build_priorities else None
 except Exception as e:out["warnings"].append(f"priority_plan_failed:{type(e).__name__}")
 try:out["campaign_plan"]=build_research_campaign_plan(workspace_id).to_dict() if build_campaigns else None
 except Exception as e:out["warnings"].append(f"campaign_plan_failed:{type(e).__name__}")
 try:out["executive_brief"]=build_executive_brief(workspace_id,objective).get("brief") if build_brief else None
 except Exception as e:out["warnings"].append(f"brief_failed:{type(e).__name__}")
 if out["warnings"]:out["status"]="partial"
 return out
