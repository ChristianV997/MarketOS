from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Body, Query
from backend.deliverables.product_validation_sprint import build_product_validation_sprint_package
from backend.deliverables.registry import get_deliverable_registry
router=APIRouter(prefix="/api/deliverables",tags=["deliverables"])
@router.post("/product-validation-sprint")
def create_product_validation(payload: dict[str,Any]=Body(default_factory=dict)):
    try:
        formats=payload.get("formats") or ["markdown","html"]
        if not isinstance(formats,list) or any(x not in {"markdown","html"} for x in formats): return {"status":"blocked","blocked_reasons":["unsupported_artifact_format"]}
        return build_product_validation_sprint_package(str(payload.get("workspace_id","default")),payload.get("sprint_id"),payload.get("snapshot_id"),payload.get("title"),payload.get("objective"),bool(payload.get("include_appendices",True)),formats).to_dict()
    except Exception as exc: return {"status":"error","error":"deliverable_generation_failed","error_type":type(exc).__name__}
@router.get("/packages")
def packages(workspace_id: str|None=Query(None),package_type: str|None=Query(None),status: str|None=Query(None),limit: int=Query(50,ge=0,le=500)):
    xs=get_deliverable_registry().list_packages(workspace_id,package_type,status,limit); return {"packages":[x.to_dict() for x in xs],"count":len(xs)}
@router.get("/packages/{package_id}")
def package(package_id: str):
    x=get_deliverable_registry().get_package(package_id); return {"status":"not_found","package_id":package_id} if x is None else {"package":x.to_dict()}
@router.get("/packages/{package_id}/markdown")
def package_markdown(package_id: str):
    x=get_deliverable_registry().get_package(package_id); return {"status":"not_found","package_id":package_id} if x is None else {"content_type":"text/markdown","content":x.to_markdown()}
@router.get("/packages/{package_id}/html")
def package_html(package_id: str):
    x=get_deliverable_registry().get_package(package_id); return {"status":"not_found","package_id":package_id} if x is None else {"content_type":"text/html","content":x.to_html_fragment()}
@router.get("/artifacts")
def artifacts(package_id: str|None=Query(None),artifact_type: str|None=Query(None),limit: int=Query(100,ge=0,le=1000)):
    xs=get_deliverable_registry().list_artifacts(package_id,artifact_type,limit); return {"artifacts":[x.to_dict() for x in xs],"count":len(xs)}
