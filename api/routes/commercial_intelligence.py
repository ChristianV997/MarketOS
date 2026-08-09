from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Body, Query
from backend.commercial_intelligence.evidence_features import extract_evidence_features
from backend.commercial_intelligence.market_analyzer import analyze_market_category
from backend.commercial_intelligence.product_analyzer import analyze_product_viability
from backend.commercial_intelligence.intelligence_runner import run_commercial_intelligence_cycle
from backend.commercial_intelligence.intelligence_registry import get_commercial_intelligence_registry
router=APIRouter(prefix="/api/commercial-intelligence",tags=["commercial-intelligence"])
def _limit(x,m): return max(1,min(int(x),m))
@router.post("/features/extract")
def features_extract(payload:dict[str,Any]=Body(default={} )):
    try: return {"status":"completed","feature_set":extract_evidence_features(payload.get("workspace_id","default"),payload.get("opportunity_id"),payload.get("category"),payload.get("product_name"),_limit(payload.get("limit",500),500)).to_dict()}
    except Exception as exc:return {"status":"partial","warnings":[str(exc)]}
@router.get("/features")
def features_list(workspace_id:str|None=None,limit:int=Query(50,le=500)): return {"status":"completed","feature_sets":[x.to_dict() for x in get_commercial_intelligence_registry().list_feature_sets(workspace_id,_limit(limit,500))]}
@router.get("/features/{feature_set_id}")
def feature_get(feature_set_id:str):
    x=get_commercial_intelligence_registry().get_feature_set(feature_set_id); return x.to_dict() if x else {"status":"not_found","feature_set_id":feature_set_id}
@router.post("/market/analyze")
def market_analyze(payload:dict[str,Any]=Body(default={} )):
    try:return {"status":"completed","market_report":analyze_market_category(payload.get("workspace_id","default"),payload.get("category_name"),payload.get("opportunity_id"),_limit(payload.get("limit",500),500)).to_dict()}
    except Exception as exc:return {"status":"partial","warnings":[str(exc)]}
@router.get("/market/reports")
def market_reports(workspace_id:str|None=None,category_name:str|None=None,limit:int=Query(50,le=500)):return {"status":"completed","market_reports":[x.to_dict() for x in get_commercial_intelligence_registry().list_market_reports(workspace_id,category_name,_limit(limit,500))]}
@router.get("/market/reports/{report_id}")
def market_report(report_id:str):
    x=get_commercial_intelligence_registry().get_market_report(report_id); return x.to_dict() if x else {"status":"not_found","report_id":report_id}
@router.post("/product/analyze")
def product_analyze(payload:dict[str,Any]=Body(default={} )):
    try:return {"status":"completed","product_report":analyze_product_viability(payload.get("workspace_id","default"),payload.get("product_name"),payload.get("category_name"),payload.get("opportunity_id"),_limit(payload.get("limit",500),500)).to_dict()}
    except Exception as exc:return {"status":"partial","warnings":[str(exc)]}
@router.get("/product/reports")
def product_reports(workspace_id:str|None=None,product_name:str|None=None,category_name:str|None=None,opportunity_id:str|None=None,limit:int=Query(50,le=500)):return {"status":"completed","product_reports":[x.to_dict() for x in get_commercial_intelligence_registry().list_product_reports(workspace_id,product_name,category_name,opportunity_id,_limit(limit,500))]}
@router.get("/product/reports/{report_id}")
def product_report(report_id:str):
    x=get_commercial_intelligence_registry().get_product_report(report_id); return x.to_dict() if x else {"status":"not_found","report_id":report_id}
@router.post("/cycle")
def cycle(payload:dict[str,Any]=Body(default={} )): return run_commercial_intelligence_cycle(payload.get("workspace_id","default"),payload.get("category_name"),payload.get("product_name"),payload.get("opportunity_id"),bool(payload.get("include_market",True)),bool(payload.get("include_product",True)))
