from __future__ import annotations
from typing import Any
from fastapi import APIRouter,Body,Query
from backend.intelligence.executive_command_runner import run_executive_intelligence_cycle
from backend.intelligence.knowledge_graph_builder import build_knowledge_graph_snapshot
from backend.intelligence.knowledge_registry import get_knowledge_registry
from backend.intelligence.strategic_priority_engine import build_strategic_priority_plan
from backend.intelligence.research_campaign_engine import build_research_campaign_plan
from backend.intelligence.executive_brief_engine import build_executive_brief
from backend.intelligence.intelligence_registry import get_intelligence_registry
router=APIRouter(prefix="/api/intelligence",tags=["intelligence"])
@router.post("/cycle")
def cycle(payload:dict[str,Any]=Body(default_factory=dict)):return run_executive_intelligence_cycle(str(payload.get("workspace_id","default")),str(payload.get("objective","Assess MarketOS strategic state and recommend next actions")),bool(payload.get("build_graph",True)),bool(payload.get("build_priorities",True)),bool(payload.get("build_campaigns",True)),bool(payload.get("build_brief",True)))
@router.post("/knowledge-graph/build")
def graph_build(payload:dict[str,Any]=Body(default_factory=dict)):return build_knowledge_graph_snapshot(str(payload.get("workspace_id","default")))
@router.get("/knowledge-graph/snapshots")
def graph_snapshots(workspace_id:str|None=Query(None),limit:int=Query(50,ge=0,le=500)):return {"snapshots":[x.to_dict() for x in get_knowledge_registry().list_snapshots(workspace_id,limit)]}
@router.get("/knowledge-graph/snapshots/{snapshot_id}")
def graph_snapshot(snapshot_id:str):
 x=get_knowledge_registry().get_snapshot(snapshot_id);return {"status":"not_found"} if x is None else {"snapshot":x.to_dict()}
@router.get("/knowledge-graph/nodes")
def graph_nodes(workspace_id:str|None=Query(None),node_type:str|None=Query(None),status:str|None=Query(None),limit:int=Query(200,ge=0,le=2000)):return {"nodes":[x.to_dict() for x in get_knowledge_registry().list_nodes(workspace_id,node_type,status,limit=limit)]}
@router.get("/knowledge-graph/nodes/{node_id}")
def graph_node(node_id:str):
 x=get_knowledge_registry().get_node(node_id);return {"status":"not_found"} if x is None else {"node":x.to_dict()}
@router.get("/knowledge-graph/nodes/{node_id}/neighbors")
def graph_neighbors(node_id:str,relation_type:str|None=Query(None),direction:str=Query("both"),limit:int=Query(100,ge=0,le=500)):return {"nodes":[x.to_dict() for x in get_knowledge_registry().neighbors(node_id,relation_type,direction,limit)]}
@router.post("/strategic-priorities/build")
def priorities_build(payload:dict[str,Any]=Body(default_factory=dict)):
 x=build_strategic_priority_plan(str(payload.get("workspace_id","default")),min(max(int(payload.get("max_priorities",20)),0),50));get_intelligence_registry().register_priority_plan(x);return {"plan":x.to_dict()}
@router.get("/strategic-priorities")
def priorities(workspace_id:str|None=Query(None),limit:int=Query(50,ge=0,le=500)):return {"plans":[x.to_dict() for x in get_intelligence_registry().list_priority_plans(workspace_id,limit)]}
@router.get("/strategic-priorities/{plan_id}")
def priority(plan_id:str):
 x=get_intelligence_registry().get_priority_plan(plan_id);return {"status":"not_found"} if x is None else {"plan":x.to_dict()}
@router.post("/research-campaigns/build")
def campaigns_build(payload:dict[str,Any]=Body(default_factory=dict)):
 x=build_research_campaign_plan(str(payload.get("workspace_id","default")),min(max(int(payload.get("max_campaigns",10)),0),20));get_intelligence_registry().register_campaign_plan(x);return {"plan":x.to_dict()}
@router.get("/research-campaigns")
def campaigns(workspace_id:str|None=Query(None),limit:int=Query(50,ge=0,le=500)):return {"plans":[x.to_dict() for x in get_intelligence_registry().list_campaign_plans(workspace_id,limit)]}
@router.get("/research-campaigns/{plan_id}")
def campaign(plan_id:str):
 x=get_intelligence_registry().get_campaign_plan(plan_id);return {"status":"not_found"} if x is None else {"plan":x.to_dict()}
@router.post("/executive-briefs/build")
def briefs_build(payload:dict[str,Any]=Body(default_factory=dict)):return build_executive_brief(str(payload.get("workspace_id","default")),str(payload.get("period_label","current")),bool(payload.get("include_html",True)))
@router.get("/executive-briefs")
def briefs(workspace_id:str|None=Query(None),limit:int=Query(50,ge=0,le=500)):return {"briefs":[x.to_dict() for x in get_intelligence_registry().list_executive_briefs(workspace_id,limit)]}
@router.get("/executive-briefs/{brief_id}")
def brief(brief_id:str):
 x=get_intelligence_registry().get_executive_brief(brief_id);return {"status":"not_found"} if x is None else {"brief":x.to_dict()}
@router.get("/executive-briefs/{brief_id}/markdown")
def brief_markdown(brief_id:str):
 x=get_intelligence_registry().get_executive_brief(brief_id);return {"status":"not_found"} if x is None else {"content_type":"text/markdown","content":x.to_markdown()}
@router.get("/executive-briefs/{brief_id}/html")
def brief_html(brief_id:str):
 x=get_intelligence_registry().get_executive_brief(brief_id);return {"status":"not_found"} if x is None else {"content_type":"text/html","content":x.to_html_fragment()}
