from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from backend.optimization.action_generator import generate_portfolio_actions
from backend.optimization.optimization_registry import get_optimization_registry
from backend.optimization.optimizer import build_portfolio_optimization_plan, optimize_actions_for_constraint
from backend.optimization.scenario import ResourceConstraint
from backend.security.auth import (
    AuthenticatedActor,
    require_authenticated,
    require_operator,
    resolve_authorized_workspace,
)

router = APIRouter(prefix="/api/optimization", tags=["optimization"])


@router.post("/actions/generate")
def generate(
    payload: dict[str, Any] = Body(default_factory=dict),
    actor: AuthenticatedActor = Depends(require_operator),
):
    try:
        requested_ws = payload.get("workspace_id")
        effective_ws = resolve_authorized_workspace(str(requested_ws) if requested_ws else None, actor)
        maximum = min(max(int(payload.get("max_actions", 100)), 0), 200)
        return {
            "action_set": generate_portfolio_actions(effective_ws, maximum).to_dict(),
            "status": "completed",
            "simulated_only": True,
        }
    except Exception as exc:
        return {"status": "error", "errors": ["action_generation_failed", type(exc).__name__]}


@router.get("/action-sets")
def action_sets(
    workspace_id: str | None = Query(None),
    limit: int = Query(50, ge=0, le=500),
    actor: AuthenticatedActor = Depends(require_authenticated),
):
    effective_ws = resolve_authorized_workspace(workspace_id, actor) if workspace_id else (None if actor.is_operator else resolve_authorized_workspace(None, actor))
    return {"action_sets": [x.to_dict() for x in get_optimization_registry().list_action_sets(effective_ws, limit)]}


@router.get("/action-sets/{action_set_id}")
def action_set(
    action_set_id: str,
    actor: AuthenticatedActor = Depends(require_authenticated),
):
    item = get_optimization_registry().get_action_set(action_set_id)
    if item is None:
        return {"status": "not_found", "action_set_id": action_set_id}
    if not actor.can_access_workspace(item.workspace_id):
        raise HTTPException(status_code=403, detail="workspace_access_denied")
    return {"action_set": item.to_dict()}


@router.post("/portfolio")
def portfolio(
    payload: dict[str, Any] = Body(default_factory=dict),
    actor: AuthenticatedActor = Depends(require_operator),
):
    try:
        requested_ws = payload.get("workspace_id")
        effective_ws = resolve_authorized_workspace(str(requested_ws) if requested_ws else None, actor)
        constraints = [ResourceConstraint.from_dict(item) for item in payload.get("constraints", [])][:20] if isinstance(payload.get("constraints"), list) else None
        plan = build_portfolio_optimization_plan(
            effective_ws,
            str(payload.get("objective", "Optimize next MarketOS actions under resource constraints")),
            constraints,
        )
        return {"plan": plan.to_dict(), "status": "completed", "simulated_only": True}
    except Exception as exc:
        return {"status": "error", "errors": ["portfolio_optimization_failed", type(exc).__name__]}


@router.get("/plans")
def plans(
    workspace_id: str | None = Query(None),
    limit: int = Query(50, ge=0, le=500),
    actor: AuthenticatedActor = Depends(require_authenticated),
):
    effective_ws = resolve_authorized_workspace(workspace_id, actor) if workspace_id else (None if actor.is_operator else resolve_authorized_workspace(None, actor))
    return {"plans": [x.to_dict() for x in get_optimization_registry().list_plans(effective_ws, limit)]}


@router.get("/plans/latest")
def latest(
    workspace_id: str | None = Query(None),
    actor: AuthenticatedActor = Depends(require_authenticated),
):
    effective_ws = resolve_authorized_workspace(workspace_id, actor) if workspace_id else (None if actor.is_operator else resolve_authorized_workspace(None, actor))
    item = get_optimization_registry().latest_plan(effective_ws)
    return {"status": "not_found"} if item is None else {"plan": item.to_dict()}


@router.get("/plans/{optimization_id}")
def plan(
    optimization_id: str,
    actor: AuthenticatedActor = Depends(require_authenticated),
):
    item = get_optimization_registry().get_plan(optimization_id)
    if item is None:
        return {"status": "not_found", "optimization_id": optimization_id}
    if not actor.can_access_workspace(item.workspace_id):
        raise HTTPException(status_code=403, detail="workspace_access_denied")
    return {"plan": item.to_dict()}


@router.post("/scenario")
def scenario(
    payload: dict[str, Any] = Body(default_factory=dict),
    actor: AuthenticatedActor = Depends(require_operator),
):
    try:
        requested_ws = payload.get("workspace_id")
        effective_ws = resolve_authorized_workspace(str(requested_ws) if requested_ws else None, actor)
        constraint = ResourceConstraint.from_dict(payload.get("constraint", {}))
        action_set_obj = (
            get_optimization_registry().get_action_set(str(payload.get("action_set_id", "")))
            if payload.get("action_set_id")
            else generate_portfolio_actions(effective_ws, 100)
        )
        if action_set_obj and not actor.can_access_workspace(action_set_obj.workspace_id):
            raise HTTPException(status_code=403, detail="workspace_access_denied")
        actions_list = action_set_obj.actions if action_set_obj else []
        result = optimize_actions_for_constraint(actions_list, constraint)
        return {"scenario": result.to_dict(), "status": "completed", "simulated_only": True}
    except HTTPException:
        raise
    except Exception as exc:
        return {"status": "error", "errors": ["scenario_optimization_failed", type(exc).__name__]}
