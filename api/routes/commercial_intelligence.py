from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Body, Depends, Query
from backend.identity.operator_gates import commercial_intelligence_run_gate
from backend.identity.workspaces import WorkspaceAccess
from api.routes._workspace_binding import bound_opportunity_id, bound_workspace, owned_or_none, verified_workspace
from backend.commercial_intelligence.evidence_features import extract_evidence_features
from backend.commercial_intelligence.market_analyzer import analyze_market_category
from backend.commercial_intelligence.product_analyzer import analyze_product_viability
from backend.commercial_intelligence.intelligence_runner import run_commercial_intelligence_cycle
from backend.commercial_intelligence.intelligence_registry import get_commercial_intelligence_registry
router=APIRouter(prefix="/api/commercial-intelligence",tags=["commercial-intelligence"])
def _limit(x,m): return max(1,min(int(x),m))
@router.post("/features/extract")
def features_extract(payload:dict[str,Any]=Body(default={} ),access:WorkspaceAccess=Depends(commercial_intelligence_run_gate)):
    workspace=bound_workspace(payload,access); opportunity_id=bound_opportunity_id(payload.get("opportunity_id"),workspace)
    try: return {"status":"completed","feature_set":extract_evidence_features(workspace,opportunity_id,payload.get("category"),payload.get("product_name"),_limit(payload.get("limit",500),500)).to_dict()}
    except Exception as exc:return {"status":"partial","warnings":[str(exc)]}
@router.get("/features")
def features_list(workspace_id:str|None=None,limit:int=Query(50,le=500),access:WorkspaceAccess=Depends(commercial_intelligence_run_gate)): return {"status":"completed","feature_sets":[x.to_dict() for x in get_commercial_intelligence_registry().list_feature_sets(verified_workspace(workspace_id,access),_limit(limit,500))]}
@router.get("/features/{feature_set_id}")
def feature_get(feature_set_id:str,access:WorkspaceAccess=Depends(commercial_intelligence_run_gate)):
    x=owned_or_none(get_commercial_intelligence_registry().get_feature_set(feature_set_id),access.workspace_id); return x.to_dict() if x else {"status":"not_found","feature_set_id":feature_set_id}
@router.post("/market/analyze")
def market_analyze(payload:dict[str,Any]=Body(default={} ),access:WorkspaceAccess=Depends(commercial_intelligence_run_gate)):
    workspace=bound_workspace(payload,access); opportunity_id=bound_opportunity_id(payload.get("opportunity_id"),workspace)
    try:return {"status":"completed","market_report":analyze_market_category(workspace,payload.get("category_name"),opportunity_id,_limit(payload.get("limit",500),500)).to_dict()}
    except Exception as exc:return {"status":"partial","warnings":[str(exc)]}
@router.get("/market/reports")
def market_reports(workspace_id:str|None=None,category_name:str|None=None,limit:int=Query(50,le=500),access:WorkspaceAccess=Depends(commercial_intelligence_run_gate)):return {"status":"completed","market_reports":[x.to_dict() for x in get_commercial_intelligence_registry().list_market_reports(verified_workspace(workspace_id,access),category_name,_limit(limit,500))]}
@router.get("/market/reports/{report_id}")
def market_report(report_id:str,access:WorkspaceAccess=Depends(commercial_intelligence_run_gate)):
    x=owned_or_none(get_commercial_intelligence_registry().get_market_report(report_id),access.workspace_id); return x.to_dict() if x else {"status":"not_found","report_id":report_id}
@router.post("/product/analyze")
def product_analyze(payload:dict[str,Any]=Body(default={} ),access:WorkspaceAccess=Depends(commercial_intelligence_run_gate)):
    workspace=bound_workspace(payload,access); opportunity_id=bound_opportunity_id(payload.get("opportunity_id"),workspace)
    try:return {"status":"completed","product_report":analyze_product_viability(workspace,payload.get("product_name"),payload.get("category_name"),opportunity_id,_limit(payload.get("limit",500),500)).to_dict()}
    except Exception as exc:return {"status":"partial","warnings":[str(exc)]}
@router.get("/product/reports")
def product_reports(workspace_id:str|None=None,product_name:str|None=None,category_name:str|None=None,opportunity_id:str|None=None,limit:int=Query(50,le=500),access:WorkspaceAccess=Depends(commercial_intelligence_run_gate)):return {"status":"completed","product_reports":[x.to_dict() for x in get_commercial_intelligence_registry().list_product_reports(verified_workspace(workspace_id,access),product_name,category_name,opportunity_id,_limit(limit,500))]}
@router.get("/product/reports/{report_id}")
def product_report(report_id:str,access:WorkspaceAccess=Depends(commercial_intelligence_run_gate)):
    x=owned_or_none(get_commercial_intelligence_registry().get_product_report(report_id),access.workspace_id); return x.to_dict() if x else {"status":"not_found","report_id":report_id}
@router.post("/cycle")
def cycle(payload:dict[str,Any]=Body(default={} ),access:WorkspaceAccess=Depends(commercial_intelligence_run_gate)):
    workspace=bound_workspace(payload,access)
    return run_commercial_intelligence_cycle(workspace,payload.get("category_name"),payload.get("product_name"),bound_opportunity_id(payload.get("opportunity_id"),workspace),bool(payload.get("include_market",True)),bool(payload.get("include_product",True)))
