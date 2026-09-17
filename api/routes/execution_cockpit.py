from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Body, Depends, HTTPException, Query

from backend.execution_cockpit.approval import create_pending_approval, decide_approval
from backend.execution_cockpit.cockpit_registry import get_cockpit_registry
from backend.execution_cockpit.executor import execute_cockpit_action, execute_cockpit_plan, preview_cockpit_plan
from backend.execution_cockpit.task_resolver import resolve_plan_to_cockpit_actions, resolve_task_to_cockpit_action
from backend.security.auth import (
    AuthenticatedActor,
    require_authenticated,
    require_operator,
    resolve_authorized_workspace,
)

router = APIRouter(prefix="/api/cockpit", tags=["execution-cockpit"])


def _limit(value: int, maximum: int) -> int:
    return max(1, min(int(value), maximum))


@router.post("/tasks/{task_id}/resolve")
def resolve_task(
    task_id: str,
    actor: AuthenticatedActor = Depends(require_operator),
):
    try:
        return {"status": "completed", "action": resolve_task_to_cockpit_action(task_id).to_dict()}
    except Exception as exc:
        return {"status": "blocked", "task_id": task_id, "blocked_reasons": [str(exc)]}


@router.post("/plans/{plan_id}/preview")
def preview_plan(
    plan_id: str,
    actor: AuthenticatedActor = Depends(require_authenticated),
):
    return preview_cockpit_plan(plan_id)


@router.post("/plans/{plan_id}/resolve")
def resolve_plan(
    plan_id: str,
    payload: dict[str, Any] = Body(default={}),
    actor: AuthenticatedActor = Depends(require_operator),
):
    try:
        return {
            "status": "completed",
            "plan_id": plan_id,
            "actions": [
                x.to_dict()
                for x in resolve_plan_to_cockpit_actions(plan_id, bool(payload.get("include_blocked", True)))
            ],
        }
    except Exception as exc:
        return {"status": "blocked", "plan_id": plan_id, "blocked_reasons": [str(exc)]}


@router.get("/actions")
def actions(
    workspace_id: str | None = None,
    status: str | None = None,
    action_type: str | None = None,
    source_task_id: str | None = None,
    limit: int = Query(100, le=500),
    actor: AuthenticatedActor = Depends(require_authenticated),
):
    effective_ws = resolve_authorized_workspace(workspace_id, actor) if workspace_id else (None if actor.is_operator else resolve_authorized_workspace(None, actor))
    return {
        "status": "completed",
        "actions": [
            x.to_dict()
            for x in get_cockpit_registry().list_actions(
                effective_ws, status, action_type, source_task_id, _limit(limit, 500)
            )
        ],
    }


@router.get("/actions/{action_id}")
def action(
    action_id: str,
    actor: AuthenticatedActor = Depends(require_authenticated),
):
    item = get_cockpit_registry().get_action(action_id)
    if not item:
        return {"status": "not_found", "action_id": action_id}
    if not actor.can_access_workspace(item.workspace_id):
        raise HTTPException(status_code=403, detail="workspace_access_denied")
    return item.to_dict()


@router.post("/actions/{action_id}/approval")
def request_approval(
    action_id: str,
    payload: dict[str, Any] = Body(default={}),
    actor: AuthenticatedActor = Depends(require_operator),
):
    item = get_cockpit_registry().get_action(action_id)
    if item is None:
        return {"status": "not_found", "action_id": action_id}
    try:
        approver = str(payload.get("approver", actor.actor_id))
        return {"status": "completed", "approval": create_pending_approval(item, approver).to_dict()}
    except Exception as exc:
        return {"status": "blocked", "action_id": action_id, "blocked_reasons": [str(exc)]}


@router.post("/approvals/{approval_id}/decide")
def decide(
    approval_id: str,
    payload: dict[str, Any] = Body(default={}),
    actor: AuthenticatedActor = Depends(require_operator),
):
    try:
        approver = str(payload.get("approver", actor.actor_id))
        return {
            "status": "completed",
            "approval": decide_approval(
                approval_id,
                str(payload.get("decision", "")),
                str(payload.get("reason", "")),
                approver,
            ).to_dict(),
        }
    except Exception as exc:
        return {"status": "blocked", "approval_id": approval_id, "blocked_reasons": [str(exc)]}


@router.get("/approvals")
def approvals(
    workspace_id: str | None = None,
    action_id: str | None = None,
    decision: str | None = None,
    limit: int = Query(100, le=500),
    actor: AuthenticatedActor = Depends(require_authenticated),
):
    effective_ws = resolve_authorized_workspace(workspace_id, actor) if workspace_id else (None if actor.is_operator else resolve_authorized_workspace(None, actor))
    return {
        "status": "completed",
        "approvals": [
            x.to_dict()
            for x in get_cockpit_registry().list_approvals(effective_ws, action_id, decision, _limit(limit, 500))
        ],
    }


@router.post("/actions/{action_id}/execute")
def execute_action(
    action_id: str,
    payload: dict[str, Any] = Body(default={}),
    actor: AuthenticatedActor = Depends(require_operator),
):
    item = get_cockpit_registry().get_action(action_id)
    if item and not actor.can_access_workspace(item.workspace_id):
        raise HTTPException(status_code=403, detail="workspace_access_denied")
    return execute_cockpit_action(action_id, payload.get("approval_id"), bool(payload.get("dry_run", False)))


@router.post("/plans/{plan_id}/execute")
def execute_plan(
    plan_id: str,
    payload: dict[str, Any] = Body(default={}),
    actor: AuthenticatedActor = Depends(require_operator),
):
    task_ids = payload.get("task_ids")
    if task_ids is not None and len(task_ids) > 100:
        return {"status": "blocked", "blocked_reasons": ["task_ids_limit"]}
    return execute_cockpit_plan(
        plan_id,
        task_ids,
        bool(payload.get("require_approval", True)),
        bool(payload.get("dry_run", False)),
        bool(payload.get("stop_on_failure", False)),
    )


@router.get("/executions")
def executions(
    workspace_id: str | None = None,
    action_id: str | None = None,
    source_task_id: str | None = None,
    status: str | None = None,
    limit: int = Query(100, le=500),
    actor: AuthenticatedActor = Depends(require_authenticated),
):
    effective_ws = resolve_authorized_workspace(workspace_id, actor) if workspace_id else (None if actor.is_operator else resolve_authorized_workspace(None, actor))
    return {
        "status": "completed",
        "executions": [
            x.to_dict()
            for x in get_cockpit_registry().list_executions(
                effective_ws, action_id, source_task_id, status, _limit(limit, 500)
            )
        ],
    }


@router.get("/executions/{execution_id}")
def execution(
    execution_id: str,
    actor: AuthenticatedActor = Depends(require_authenticated),
):
    item = get_cockpit_registry().get_execution(execution_id)
    if not item:
        return {"status": "not_found", "execution_id": execution_id}
    if not actor.can_access_workspace(item.workspace_id):
        raise HTTPException(status_code=403, detail="workspace_access_denied")
    return item.to_dict()


@router.get("/executions/{execution_id}/checkpoints")
def checkpoints(
    execution_id: str,
    limit: int = Query(200, le=1000),
    actor: AuthenticatedActor = Depends(require_authenticated),
):
    item = get_cockpit_registry().get_execution(execution_id)
    if item and not actor.can_access_workspace(item.workspace_id):
        raise HTTPException(status_code=403, detail="workspace_access_denied")
    return {
        "status": "completed",
        "checkpoints": [
            x.to_dict()
            for x in get_cockpit_registry().list_checkpoints(execution_id=execution_id, limit=_limit(limit, 1000))
        ],
    }


@router.get("/summaries")
def summaries(
    workspace_id: str | None = None,
    plan_id: str | None = None,
    limit: int = Query(100, le=500),
    actor: AuthenticatedActor = Depends(require_authenticated),
):
    effective_ws = resolve_authorized_workspace(workspace_id, actor) if workspace_id else (None if actor.is_operator else resolve_authorized_workspace(None, actor))
    return {
        "status": "completed",
        "summaries": [
            x.to_dict() for x in get_cockpit_registry().list_summaries(effective_ws, plan_id, _limit(limit, 500))
        ],
    }


@router.get("/summaries/{summary_id}")
def summary(
    summary_id: str,
    actor: AuthenticatedActor = Depends(require_authenticated),
):
    item = get_cockpit_registry().get_summary(summary_id)
    if not item:
        return {"status": "not_found", "summary_id": summary_id}
    if not actor.can_access_workspace(item.workspace_id):
        raise HTTPException(status_code=403, detail="workspace_access_denied")
    return item.to_dict()
