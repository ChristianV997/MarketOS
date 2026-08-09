from __future__ import annotations
import uuid
from .executive_brief import ExecutiveBrief
from .knowledge_graph_builder import build_knowledge_graph_snapshot
from .strategic_priority_engine import build_strategic_priority_plan
from .research_campaign_engine import build_research_campaign_plan
from .intelligence_registry import get_intelligence_registry
from .knowledge_registry import get_knowledge_registry
from backend.discovery.opportunity_registry import get_opportunity_registry
from backend.discovery.validation_sprint_registry import get_validation_sprint_registry
from backend.deliverables.registry import get_deliverable_registry
from pathlib import Path
def build_executive_brief(workspace_id="default",period_label="current",include_html=True):
 graph=build_knowledge_graph_snapshot(workspace_id);priority=build_strategic_priority_plan(workspace_id);campaign=build_research_campaign_plan(workspace_id);reg=get_intelligence_registry();reg.register_priority_plan(priority);reg.register_campaign_plan(campaign);opp=get_opportunity_registry().list_opportunities(workspace_id,limit=10);sprints=get_validation_sprint_registry().list_sprints(workspace_id,limit=10);packages=get_deliverable_registry().list_packages(workspace_id,limit=10);previous=reg.latest_executive_brief(workspace_id); changes=[f"Knowledge graph now contains {graph['snapshot']['node_count']} nodes and {graph['snapshot']['edge_count']} edges.",f"Priority plan contains {len(priority.priorities)} open priorities."]
 optimization=None
 try:
  from backend.optimization.optimization_registry import get_optimization_registry
  optimization=get_optimization_registry().latest_plan(workspace_id)
 except Exception: pass
 if optimization: changes.append(f"Latest optimization plan recommends {len(optimization.recommended_actions)} simulated action(s) under scenario `{optimization.recommended_scenario_id}`.")
 if previous:changes.append("A previous executive brief exists; this brief is a subsequent recorded state.")
 brief=ExecutiveBrief("brief_"+uuid.uuid4().hex[:16],workspace_id,"Executive Intelligence Brief",period_label,"MarketOS has a deterministic, evidence-constrained view of current opportunities, gaps, priorities, and research work.",changes,[x.to_dict() for x in priority.priorities[:10]],[{"opportunity_id":x.opportunity_id,"name":x.name,"stage":x.stage,"score":x.score,"confidence":x.confidence} for x in opp],{"sprint_count":len(sprints),"latest_sprint_id":sprints[0].sprint_id if sprints else ""},{"graph_nodes":graph['snapshot']['node_count']},{"package_count":len(packages)},priority.top_risks,priority.top_blockers,[x.recommended_action for x in priority.priorities[:5]],priority.plan_id,campaign.plan_id,graph["snapshot"]["snapshot_id"],metadata={"include_html":include_html,"dry_run_only":True,"optimization_plan_id":optimization.optimization_id if optimization else "","optimization_summary":optimization.summary if optimization else "","recommended_scenario_id":optimization.recommended_scenario_id if optimization else "","simulated_budget_assumptions":[x.constraint.to_dict() for x in optimization.scenarios] if optimization else []})
 reg.register_executive_brief(brief)
 try:
  root=Path("state/executive_briefs");root.mkdir(parents=True,exist_ok=True);(root/(brief.brief_id+".md")).write_text(brief.to_markdown(),encoding="utf-8")
  if include_html:(root/(brief.brief_id+".html")).write_text("<!doctype html><html><body>"+brief.to_html_fragment()+"</body></html>",encoding="utf-8")
 except Exception: pass
 try:
  from backend.obsidian.sync import sync_knowledge_graph_snapshot_note,sync_strategic_priority_plan_note,sync_research_campaign_plan_note,sync_executive_brief_note
  obsidian={"graph":sync_knowledge_graph_snapshot_note(get_knowledge_registry().get_snapshot(graph["snapshot"]["snapshot_id"])),"priorities":sync_strategic_priority_plan_note(priority),"campaigns":sync_research_campaign_plan_note(campaign),"brief":sync_executive_brief_note(brief)}
 except Exception as exc: obsidian={"status":"warning","error":type(exc).__name__}
 return {"brief":brief.to_dict(),"priority_plan":priority.to_dict(),"campaign_plan":campaign.to_dict(),"knowledge_graph":graph,"obsidian":obsidian,"status":"completed"}
