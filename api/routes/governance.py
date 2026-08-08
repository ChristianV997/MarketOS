from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Query

from backend.governance.registry import get_governance_registry
from backend.organization.planner_executor_reviewer import run_planner_executor_reviewer
from backend.organization.service_contract import get_service_contract_registry

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


@router.get("/proposals/{proposal_id}/decisions")
def proposal_decisions(proposal_id: str) -> dict:
    return {"proposal_id": proposal_id, "decisions": [d.to_dict() for d in get_governance_registry().list_decisions(proposal_id)]}


@router.get("/service-contracts")
def service_contracts() -> dict:
    return {"services": [item.to_dict() for item in get_service_contract_registry().list()]}


@router.post("/proposals/{proposal_id}/transition")
def transition_proposal(proposal_id: str, payload: dict[str, Any] = Body(default_factory=dict)) -> dict:
    try:
        registry = get_governance_registry(); item = registry.get_proposal(proposal_id)
        if item is None: return {"status": "not_found", "proposal_id": proposal_id}
        result = item.transition(str(payload.get("status", "")), str(payload.get("reason", "")))
        registry.register_proposal(item)
        return {"status": "ok" if result["allowed"] else "invalid_transition", "transition": result, "proposal": item.to_dict()}
    except Exception as exc:
        return {"status": "error", "error_type": type(exc).__name__, "error": "proposal_transition_failed"}


@router.post("/run-loop")
def run_loop(payload: dict[str, Any] = Body(default_factory=dict)) -> dict:
    try:
        if not isinstance(payload, dict):
            return {"status": "error", "error": "payload_must_be_object"}
        return run_planner_executor_reviewer(
            objective=str(payload.get("objective", "")), workspace=payload.get("workspace", payload.get("workspace_id", "default")),
            department_id=str(payload.get("department_id", payload.get("department", "strategy"))),
            service_name=str(payload.get("service_name", payload.get("service", ""))), inputs=payload.get("inputs") or {},
            planner_agent_id=str(payload.get("planner_agent_id", "")), executor_agent_id=str(payload.get("executor_agent_id", "")),
            reviewer_agent_id=str(payload.get("reviewer_agent_id", "")), live_action_requested=bool(payload.get("live_action_requested", False)),
        )
    except Exception as exc:
        return {"status": "error", "error_type": type(exc).__name__, "error": "governance_loop_failed"}
