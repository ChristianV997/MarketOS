from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Query

from backend.optimization.action_generator import generate_portfolio_actions
from backend.optimization.optimization_registry import get_optimization_registry
from backend.optimization.optimizer import build_portfolio_optimization_plan, optimize_actions_for_constraint
from backend.optimization.portfolio_actions import PortfolioActionSet
from backend.optimization.scenario import ResourceConstraint

router = APIRouter(prefix="/api/optimization", tags=["optimization"])


@router.post("/actions/generate")
def generate(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        maximum = min(max(int(payload.get("max_actions", 100)), 0), 200)
        return {"action_set": generate_portfolio_actions(str(payload.get("workspace_id", "default")), maximum).to_dict(), "status": "completed", "simulated_only": True}
    except Exception as exc:
        return {"status": "error", "errors": ["action_generation_failed", type(exc).__name__]}


@router.get("/action-sets")
def action_sets(workspace_id: str | None = Query(None), limit: int = Query(50, ge=0, le=500)):
    return {"action_sets": [x.to_dict() for x in get_optimization_registry().list_action_sets(workspace_id, limit)]}


@router.get("/action-sets/{action_set_id}")
def action_set(action_set_id: str):
    item = get_optimization_registry().get_action_set(action_set_id)
    return {"status": "not_found", "action_set_id": action_set_id} if item is None else {"action_set": item.to_dict()}


@router.post("/portfolio")
def portfolio(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        constraints = [ResourceConstraint.from_dict(item) for item in payload.get("constraints", [])][:20] if isinstance(payload.get("constraints"), list) else None
        plan = build_portfolio_optimization_plan(str(payload.get("workspace_id", "default")), str(payload.get("objective", "Optimize next MarketOS actions under resource constraints")), constraints)
        return {"plan": plan.to_dict(), "status": "completed", "simulated_only": True}
    except Exception as exc:
        return {"status": "error", "errors": ["portfolio_optimization_failed", type(exc).__name__]}


@router.get("/plans")
def plans(workspace_id: str | None = Query(None), limit: int = Query(50, ge=0, le=500)):
    return {"plans": [x.to_dict() for x in get_optimization_registry().list_plans(workspace_id, limit)]}


@router.get("/plans/latest")
def latest(workspace_id: str | None = Query(None)):
    item = get_optimization_registry().latest_plan(workspace_id)
    return {"status": "not_found"} if item is None else {"plan": item.to_dict()}


@router.get("/plans/{optimization_id}")
def plan(optimization_id: str):
    item = get_optimization_registry().get_plan(optimization_id)
    return {"status": "not_found", "optimization_id": optimization_id} if item is None else {"plan": item.to_dict()}


@router.post("/scenario")
def scenario(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        constraint = ResourceConstraint.from_dict(payload.get("constraint", {}))
        action_set = get_optimization_registry().get_action_set(str(payload.get("action_set_id", ""))) if payload.get("action_set_id") else generate_portfolio_actions(str(payload.get("workspace_id", "default")), 100)
        result = optimize_actions_for_constraint(action_set.actions, constraint)
        return {"scenario": result.to_dict(), "status": "completed", "simulated_only": True}
    except Exception as exc:
        return {"status": "error", "errors": ["scenario_optimization_failed", type(exc).__name__]}
