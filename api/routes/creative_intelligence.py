from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Body, Query
from backend.creative_intelligence.buyer_psychology import build_buyer_psychology_map
from backend.creative_intelligence.angle_generator import generate_creative_angles
from backend.creative_intelligence.hook_generator import generate_hooks_for_angles
from backend.creative_intelligence.claim_safety import sanitize_creative_claim
from backend.creative_intelligence.creative_runner import run_creative_intelligence_cycle
from backend.creative_intelligence.creative_registry import get_creative_registry
router=APIRouter(prefix="/api/creative-intelligence",tags=["creative-intelligence"])
def _cap(value,maximum): return min(max(int(value or 1),1),maximum)
@router.post("/cycle")
def cycle(payload:dict[str,Any]=Body(default={})): return run_creative_intelligence_cycle(payload.get("workspace_id","default"),payload.get("product_name"),payload.get("category_name"),payload.get("opportunity_id"))
@router.post("/buyer-psychology")
def buyer(payload:dict[str,Any]=Body(default={})): return {"status":"completed","buyer_psychology_map":build_buyer_psychology_map(payload.get("workspace_id","default"),payload.get("product_name"),payload.get("category_name"),payload.get("opportunity_id")).to_dict()}
@router.post("/angles/generate")
def angles(payload:dict[str,Any]=Body(default={})): return {"status":"completed","angles":[x.to_dict() for x in generate_creative_angles(payload.get("workspace_id","default"),payload.get("product_name"),payload.get("category_name"),payload.get("opportunity_id"),_cap(payload.get("max_angles",12),25))]}
@router.post("/hooks/generate")
def hooks(payload:dict[str,Any]=Body(default={})): 
 reg=get_creative_registry(); ids=payload.get("angle_ids",[])[:500];return {"status":"completed","hooks":[x.to_dict() for x in generate_hooks_for_angles([reg.get_angle(i) for i in ids if reg.get_angle(i)],_cap(payload.get("hooks_per_angle",5),10))]}
@router.get("/reports")
def reports(workspace_id:str|None=None,opportunity_id:str|None=None,product_name:str|None=None,category_name:str|None=None,limit:int=Query(50,le=500)):return {"status":"completed","reports":[x.to_dict() for x in get_creative_registry().list_reports(workspace_id,opportunity_id,product_name,category_name,limit=limit)]}
@router.get("/reports/{report_id}")
def report(report_id:str):
 x=get_creative_registry().get_report(report_id);return x.to_dict() if x else {"status":"not_found","report_id":report_id}
def _items(name,workspace_id=None,opportunity_id=None,product_name=None,angle_id=None,limit=50):
 reg=get_creative_registry();return {"status":"completed",name:[x.to_dict() for x in getattr(reg,"list_"+name)(workspace_id,opportunity_id,product_name,None,angle_id,limit)]}
@router.get("/angles")
def list_angles(workspace_id:str|None=None,opportunity_id:str|None=None,product_name:str|None=None,limit:int=Query(100,le=500)):return _items("angles",workspace_id,opportunity_id,product_name,limit=limit)
@router.get("/hooks")
def list_hooks(workspace_id:str|None=None,angle_id:str|None=None,opportunity_id:str|None=None,limit:int=Query(200,le=500)):return _items("hooks",workspace_id,opportunity_id,angle_id=angle_id,limit=limit)
@router.get("/ugc-briefs")
def list_ugc(workspace_id:str|None=None,opportunity_id:str|None=None,limit:int=Query(100,le=500)):return _items("ugc_briefs",workspace_id,opportunity_id,limit=limit)
@router.get("/storyboards")
def list_storyboards(workspace_id:str|None=None,opportunity_id:str|None=None,limit:int=Query(100,le=500)):return _items("storyboards",workspace_id,opportunity_id,limit=limit)
@router.get("/claim-maps")
def list_claim_maps(workspace_id:str|None=None,opportunity_id:str|None=None,limit:int=Query(50,le=500)):return _items("claim_maps",workspace_id,opportunity_id,limit=limit)
@router.get("/test-matrices")
def list_matrices(workspace_id:str|None=None,opportunity_id:str|None=None,limit:int=Query(50,le=500)):return _items("test_matrices",workspace_id,opportunity_id,limit=limit)
@router.post("/claims/validate")
def validate_claim(payload:dict[str,Any]=Body(default={})):return sanitize_creative_claim(str(payload.get("claim","") or ""),[],payload)
