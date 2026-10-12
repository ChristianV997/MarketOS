"""Workflow orchestration API.

Every route is operator-only (``api/routes/event_access.py``) and bound to the verified principal's workspace. A
caller-supplied ``workspace_id`` may only repeat that workspace. A workflow outside it answers exactly as a missing
one does, so a foreign workflow id is not an existence oracle.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query

from api.routes.event_access import admit_event_read, event_read_gate, event_write_gate
from backend.identity.errors import WorkspaceAccessDenied
from backend.identity.http import http_exception
from backend.identity.workspaces import WorkspaceAccess
from backend.workflows.orchestrator import replay_workflow_stage, resume_workflow, run_workflow
from backend.workflows.runbook import get_workflow_runbook, list_workflow_runbooks
from backend.workflows.workflow_registry import get_workflow_registry
from backend.workflows.workflow_summary import build_workflow_summary

# Throttled before identity, as every event-derived surface is (see api/routes/event_access.py).
router = APIRouter(prefix="/api/workflows", tags=["workflows"], dependencies=[Depends(admit_event_read)])
NOT_FOUND = "not_found"


def _scoped(selector: str | None, access: WorkspaceAccess) -> str:
    """The bound workspace when no selector is given; any other selector is refused, never widened."""
    if selector is None:
        return access.workspace_id
    if selector != access.workspace_id:
        raise http_exception(WorkspaceAccessDenied())
    return access.workspace_id


def _owned(workflow_id: str, access: WorkspaceAccess):
    record = get_workflow_registry().get_workflow(workflow_id)
    return record if record is not None and record.workspace_id == access.workspace_id else None


@router.post("/run")
def run(payload: dict[str, Any] = Body(default_factory=dict), access: WorkspaceAccess = Depends(event_write_gate)):
    requested = payload.get("workspace_id")
    return run_workflow(
        _scoped(None if requested is None else str(requested), access),
        str(payload.get("workflow_type", "full_market_cycle")),
        payload.get("title"),
        payload.get("objective"),
        payload.get("payload") or {},
        stop_after_stage=payload.get("stop_after_stage"),
    )


@router.post("/{workflow_id}/resume")
def resume(workflow_id: str, payload: dict[str, Any] = Body(default_factory=dict), access: WorkspaceAccess = Depends(event_write_gate)):
    if _owned(workflow_id, access) is None:
        return {"status": NOT_FOUND, "workflow_id": workflow_id}
    return resume_workflow(workflow_id, payload.get("from_stage"), payload.get("checkpoint_id"))


@router.post("/{workflow_id}/replay-stage")
def replay(workflow_id: str, payload: dict[str, Any] = Body(default_factory=dict), access: WorkspaceAccess = Depends(event_write_gate)):
    if _owned(workflow_id, access) is None:
        return {"status": NOT_FOUND, "workflow_id": workflow_id}
    return replay_workflow_stage(workflow_id, str(payload.get("stage_name", "")), str(payload.get("reason", "manual_replay")))


@router.get("")
def workflows(
    workspace_id: str | None = Query(None),
    workflow_type: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=0, le=500),
    access: WorkspaceAccess = Depends(event_read_gate),
):
    scope = _scoped(workspace_id, access)
    return {"workflows": [x.to_dict() for x in get_workflow_registry().list_workflows(scope, workflow_type, status, limit)]}


@router.get("/runbooks", dependencies=[Depends(event_read_gate)])
def runbooks():
    return {"runbooks": [x.to_dict() for x in list_workflow_runbooks()]}


@router.get("/runbooks/{workflow_type}", dependencies=[Depends(event_read_gate)])
def runbook(workflow_type: str):
    try:
        return {"runbook": get_workflow_runbook(workflow_type).to_dict()}
    except ValueError:
        return {"status": NOT_FOUND, "workflow_type": workflow_type}


@router.get("/{workflow_id}")
def workflow(workflow_id: str, access: WorkspaceAccess = Depends(event_read_gate)):
    record = _owned(workflow_id, access)
    return {"status": NOT_FOUND, "workflow_id": workflow_id} if record is None else {"workflow": record.to_dict()}


@router.get("/{workflow_id}/checkpoints")
def checkpoints(workflow_id: str, limit: int = Query(200, ge=0, le=1000), access: WorkspaceAccess = Depends(event_read_gate)):
    if _owned(workflow_id, access) is None:
        return {"checkpoints": []}
    return {"checkpoints": [x.to_dict() for x in get_workflow_registry().list_checkpoints(workflow_id, limit=limit)]}


@router.get("/{workflow_id}/timeline")
def timeline(workflow_id: str, limit: int = Query(500, ge=0, le=2000), access: WorkspaceAccess = Depends(event_read_gate)):
    if _owned(workflow_id, access) is None:
        return {"timeline": []}
    return {"timeline": [x.to_dict() for x in get_workflow_registry().list_timeline(workflow_id, limit=limit)]}


@router.get("/{workflow_id}/summary")
def summary(workflow_id: str, access: WorkspaceAccess = Depends(event_read_gate)):
    record = _owned(workflow_id, access)
    return {"status": NOT_FOUND, "workflow_id": workflow_id} if record is None else build_workflow_summary(record)
