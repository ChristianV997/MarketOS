from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Query

from backend.governance.registry import get_governance_registry
from backend.organization.planner_executor_reviewer import run_planner_executor_reviewer

router = APIRouter(prefix="/api/governance", tags=["governance"])


@router.get("/proposals")
def proposals(workspace_id: str | None = Query(default=None), status: str | None = Query(default=None)) -> dict:
    registry = get_governance_registry()
    return {"proposals": [p.to_dict() for p in registry.list_proposals(workspace_id, status)]}


@router.get("/proposals/{proposal_id}")
def proposal(proposal_id: str) -> dict:
    registry = get_governance_registry(); item = registry.get_proposal(proposal_id)
    if item is None: return {"status": "not_found", "proposal_id": proposal_id}
    return {"proposal": item.to_dict(), "decisions": [d.to_dict() for d in registry.list_decisions(proposal_id)]}


@router.post("/run-loop")
def run_loop(payload: dict[str, Any] = Body(default_factory=dict)) -> dict:
    return run_planner_executor_reviewer(
        objective=str(payload.get("objective", "")), workspace=payload.get("workspace", payload.get("workspace_id", "default")),
        department_id=str(payload.get("department_id", payload.get("department", "strategy"))),
        service_name=str(payload.get("service_name", payload.get("service", ""))), inputs=payload.get("inputs") or {},
        planner_agent_id=str(payload.get("planner_agent_id", "")), executor_agent_id=str(payload.get("executor_agent_id", "")),
        reviewer_agent_id=str(payload.get("reviewer_agent_id", "")), live_action_requested=bool(payload.get("live_action_requested", False)),
    )
