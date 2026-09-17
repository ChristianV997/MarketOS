from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Body, Depends, HTTPException, Query

from backend.security.auth import (
    AuthenticatedActor,
    require_authenticated,
    require_operator,
    resolve_authorized_workspace,
)
from backend.workflows.orchestrator import replay_workflow_stage, resume_workflow, run_workflow
from backend.workflows.runbook import get_workflow_runbook, list_workflow_runbooks
from backend.workflows.workflow_registry import get_workflow_registry
from backend.workflows.workflow_summary import build_workflow_summary

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


@router.post("/run")
def run(
    payload: dict[str, Any] = Body(default_factory=dict),
    actor: AuthenticatedActor = Depends(require_operator),
):
    requested_ws = payload.get("workspace_id")
    effective_ws = resolve_authorized_workspace(str(requested_ws) if requested_ws else None, actor)
    return run_workflow(
        effective_ws,
        str(payload.get("workflow_type", "full_market_cycle")),
        payload.get("title"),
        payload.get("objective"),
        payload.get("payload") or {},
        stop_after_stage=payload.get("stop_after_stage"),
    )


@router.post("/{workflow_id}/resume")
def resume(
    workflow_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    actor: AuthenticatedActor = Depends(require_operator),
):
    wf = get_workflow_registry().get_workflow(workflow_id)
    if wf and not actor.can_access_workspace(wf.workspace_id):
        raise HTTPException(status_code=403, detail="workspace_access_denied")
    return resume_workflow(workflow_id, payload.get("from_stage"), payload.get("checkpoint_id"))


@router.post("/{workflow_id}/replay-stage")
def replay(
    workflow_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    actor: AuthenticatedActor = Depends(require_operator),
):
    wf = get_workflow_registry().get_workflow(workflow_id)
    if wf and not actor.can_access_workspace(wf.workspace_id):
        raise HTTPException(status_code=403, detail="workspace_access_denied")
    return replay_workflow_stage(
        workflow_id,
        str(payload.get("stage_name", "")),
        str(payload.get("reason", "manual_replay")),
    )


@router.get("")
def workflows(
    workspace_id: str | None = Query(None),
    workflow_type: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=0, le=500),
    actor: AuthenticatedActor = Depends(require_authenticated),
):
    effective_ws = resolve_authorized_workspace(workspace_id, actor) if workspace_id else (None if actor.is_operator else resolve_authorized_workspace(None, actor))
    return {
        "workflows": [
            x.to_dict()
            for x in get_workflow_registry().list_workflows(effective_ws, workflow_type, status, limit)
        ]
    }


@router.get("/runbooks")
def runbooks(actor: AuthenticatedActor = Depends(require_authenticated)):
    return {"runbooks": [x.to_dict() for x in list_workflow_runbooks()]}


@router.get("/runbooks/{workflow_type}")
def runbook(
    workflow_type: str,
    actor: AuthenticatedActor = Depends(require_authenticated),
):
    try:
        return {"runbook": get_workflow_runbook(workflow_type).to_dict()}
    except ValueError:
        return {"status": "not_found", "workflow_type": workflow_type}


@router.get("/{workflow_id}")
def workflow(
    workflow_id: str,
    actor: AuthenticatedActor = Depends(require_authenticated),
):
    x = get_workflow_registry().get_workflow(workflow_id)
    if x is None:
        return {"status": "not_found", "workflow_id": workflow_id}
    if not actor.can_access_workspace(x.workspace_id):
        raise HTTPException(status_code=403, detail="workspace_access_denied")
    return {"workflow": x.to_dict()}


@router.get("/{workflow_id}/checkpoints")
def checkpoints(
    workflow_id: str,
    limit: int = Query(200, ge=0, le=1000),
    actor: AuthenticatedActor = Depends(require_authenticated),
):
    x = get_workflow_registry().get_workflow(workflow_id)
    if x and not actor.can_access_workspace(x.workspace_id):
        raise HTTPException(status_code=403, detail="workspace_access_denied")
    return {"checkpoints": [item.to_dict() for item in get_workflow_registry().list_checkpoints(workflow_id, limit=limit)]}


@router.get("/{workflow_id}/timeline")
def timeline(
    workflow_id: str,
    limit: int = Query(500, ge=0, le=2000),
    actor: AuthenticatedActor = Depends(require_authenticated),
):
    x = get_workflow_registry().get_workflow(workflow_id)
    if x and not actor.can_access_workspace(x.workspace_id):
        raise HTTPException(status_code=403, detail="workspace_access_denied")
    return {"timeline": [item.to_dict() for item in get_workflow_registry().list_timeline(workflow_id, limit=limit)]}


@router.get("/{workflow_id}/summary")
def summary(
    workflow_id: str,
    actor: AuthenticatedActor = Depends(require_authenticated),
):
    x = get_workflow_registry().get_workflow(workflow_id)
    if x is None:
        return {"status": "not_found", "workflow_id": workflow_id}
    if not actor.can_access_workspace(x.workspace_id):
        raise HTTPException(status_code=403, detail="workspace_access_denied")
    return build_workflow_summary(x)
