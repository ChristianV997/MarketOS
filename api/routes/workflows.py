from __future__ import annotations
from typing import Any
from fastapi import APIRouter,Body,Query
from backend.workflows.orchestrator import run_workflow,resume_workflow,replay_workflow_stage
from backend.workflows.workflow_registry import get_workflow_registry
from backend.workflows.runbook import list_workflow_runbooks,get_workflow_runbook
from backend.workflows.workflow_summary import build_workflow_summary
router=APIRouter(prefix="/api/workflows",tags=["workflows"])
@router.post("/run")
def run(payload:dict[str,Any]=Body(default_factory=dict)):return run_workflow(str(payload.get("workspace_id","default")),str(payload.get("workflow_type","full_market_cycle")),payload.get("title"),payload.get("objective"),payload.get("payload") or {},stop_after_stage=payload.get("stop_after_stage"))
@router.post("/{workflow_id}/resume")
def resume(workflow_id:str,payload:dict[str,Any]=Body(default_factory=dict)):return resume_workflow(workflow_id,payload.get("from_stage"),payload.get("checkpoint_id"))
@router.post("/{workflow_id}/replay-stage")
def replay(workflow_id:str,payload:dict[str,Any]=Body(default_factory=dict)):return replay_workflow_stage(workflow_id,str(payload.get("stage_name","")),str(payload.get("reason","manual_replay")))
@router.get("")
def workflows(workspace_id:str|None=Query(None),workflow_type:str|None=Query(None),status:str|None=Query(None),limit:int=Query(50,ge=0,le=500)):return {"workflows":[x.to_dict() for x in get_workflow_registry().list_workflows(workspace_id,workflow_type,status,limit)]}
@router.get("/runbooks")
def runbooks():return {"runbooks":[x.to_dict() for x in list_workflow_runbooks()]}
@router.get("/runbooks/{workflow_type}")
def runbook(workflow_type:str):
 try:return {"runbook":get_workflow_runbook(workflow_type).to_dict()}
 except ValueError:return {"status":"not_found","workflow_type":workflow_type}
@router.get("/{workflow_id}")
def workflow(workflow_id:str):
 x=get_workflow_registry().get_workflow(workflow_id);return {"status":"not_found","workflow_id":workflow_id} if x is None else {"workflow":x.to_dict()}
@router.get("/{workflow_id}/checkpoints")
def checkpoints(workflow_id:str,limit:int=Query(200,ge=0,le=1000)):return {"checkpoints":[x.to_dict() for x in get_workflow_registry().list_checkpoints(workflow_id,limit=limit)]}
@router.get("/{workflow_id}/timeline")
def timeline(workflow_id:str,limit:int=Query(500,ge=0,le=2000)):return {"timeline":[x.to_dict() for x in get_workflow_registry().list_timeline(workflow_id,limit=limit)]}
@router.get("/{workflow_id}/summary")
def summary(workflow_id:str):
 x=get_workflow_registry().get_workflow(workflow_id);return {"status":"not_found","workflow_id":workflow_id} if x is None else build_workflow_summary(x)
