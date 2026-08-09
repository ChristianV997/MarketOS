from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Body, Query

from backend.execution_cockpit.approval import create_pending_approval, decide_approval
from backend.execution_cockpit.cockpit_registry import get_cockpit_registry
from backend.execution_cockpit.executor import execute_cockpit_action, execute_cockpit_plan, preview_cockpit_plan
from backend.execution_cockpit.task_resolver import resolve_plan_to_cockpit_actions, resolve_task_to_cockpit_action

router = APIRouter(prefix="/api/cockpit", tags=["execution-cockpit"])

def _limit(value, maximum): return max(1, min(int(value), maximum))

@router.post("/tasks/{task_id}/resolve")
def resolve_task(task_id: str):
    try: return {"status": "completed", "action": resolve_task_to_cockpit_action(task_id).to_dict()}
    except Exception as exc: return {"status": "blocked", "task_id": task_id, "blocked_reasons": [str(exc)]}

@router.post("/plans/{plan_id}/preview")
def preview_plan(plan_id: str): return preview_cockpit_plan(plan_id)

@router.post("/plans/{plan_id}/resolve")
def resolve_plan(plan_id: str, payload: dict[str, Any] = Body(default={} )):
    try: return {"status": "completed", "plan_id": plan_id, "actions": [x.to_dict() for x in resolve_plan_to_cockpit_actions(plan_id, bool(payload.get("include_blocked", True)))]}
    except Exception as exc: return {"status": "blocked", "plan_id": plan_id, "blocked_reasons": [str(exc)]}

@router.get("/actions")
def actions(workspace_id: str | None = None, status: str | None = None, action_type: str | None = None, source_task_id: str | None = None, limit: int = Query(100, le=500)):
    return {"status": "completed", "actions": [x.to_dict() for x in get_cockpit_registry().list_actions(workspace_id, status, action_type, source_task_id, _limit(limit, 500))]}

@router.get("/actions/{action_id}")
def action(action_id: str):
    item = get_cockpit_registry().get_action(action_id); return item.to_dict() if item else {"status": "not_found", "action_id": action_id}

@router.post("/actions/{action_id}/approval")
def request_approval(action_id: str, payload: dict[str, Any] = Body(default={} )):
    item = get_cockpit_registry().get_action(action_id)
    if item is None: return {"status": "not_found", "action_id": action_id}
    try: return {"status": "completed", "approval": create_pending_approval(item, str(payload.get("approver", "operator"))).to_dict()}
    except Exception as exc: return {"status": "blocked", "action_id": action_id, "blocked_reasons": [str(exc)]}

@router.post("/approvals/{approval_id}/decide")
def decide(approval_id: str, payload: dict[str, Any] = Body(default={} )):
    try: return {"status": "completed", "approval": decide_approval(approval_id, str(payload.get("decision", "")), str(payload.get("reason", "")), str(payload.get("approver", "operator"))).to_dict()}
    except Exception as exc: return {"status": "blocked", "approval_id": approval_id, "blocked_reasons": [str(exc)]}

@router.get("/approvals")
def approvals(workspace_id: str | None = None, action_id: str | None = None, decision: str | None = None, limit: int = Query(100, le=500)):
    return {"status": "completed", "approvals": [x.to_dict() for x in get_cockpit_registry().list_approvals(workspace_id, action_id, decision, _limit(limit, 500))]}

@router.post("/actions/{action_id}/execute")
def execute_action(action_id: str, payload: dict[str, Any] = Body(default={} )):
    return execute_cockpit_action(action_id, payload.get("approval_id"), bool(payload.get("dry_run", False)))

@router.post("/plans/{plan_id}/execute")
def execute_plan(plan_id: str, payload: dict[str, Any] = Body(default={} )):
    task_ids = payload.get("task_ids")
    if task_ids is not None and len(task_ids) > 100: return {"status": "blocked", "blocked_reasons": ["task_ids_limit"]}
    return execute_cockpit_plan(plan_id, task_ids, bool(payload.get("require_approval", True)), bool(payload.get("dry_run", False)), bool(payload.get("stop_on_failure", False)))

@router.get("/executions")
def executions(workspace_id: str | None = None, action_id: str | None = None, source_task_id: str | None = None, status: str | None = None, limit: int = Query(100, le=500)):
    return {"status": "completed", "executions": [x.to_dict() for x in get_cockpit_registry().list_executions(workspace_id, action_id, source_task_id, status, _limit(limit, 500))]}

@router.get("/executions/{execution_id}")
def execution(execution_id: str):
    item = get_cockpit_registry().get_execution(execution_id); return item.to_dict() if item else {"status": "not_found", "execution_id": execution_id}

@router.get("/executions/{execution_id}/checkpoints")
def checkpoints(execution_id: str, limit: int = Query(200, le=1000)):
    return {"status": "completed", "checkpoints": [x.to_dict() for x in get_cockpit_registry().list_checkpoints(execution_id=execution_id, limit=_limit(limit, 1000))]}

@router.get("/summaries")
def summaries(workspace_id: str | None = None, plan_id: str | None = None, limit: int = Query(100, le=500)):
    return {"status": "completed", "summaries": [x.to_dict() for x in get_cockpit_registry().list_summaries(workspace_id, plan_id, _limit(limit, 500))]}

@router.get("/summaries/{summary_id}")
def summary(summary_id: str):
    item = get_cockpit_registry().get_summary(summary_id); return item.to_dict() if item else {"status": "not_found", "summary_id": summary_id}
