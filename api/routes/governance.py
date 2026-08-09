from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Query

from backend.governance.registry import get_governance_registry
from backend.organization.planner_executor_reviewer import run_planner_executor_reviewer
from backend.organization.service_contract import get_service_contract_registry
from backend.organization.portfolio_report import build_portfolio_report
from backend.organization.report_registry import get_report_registry
from backend.obsidian.sync import sync_portfolio_report_note

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


@router.get("/reports")
def reports(workspace_id: str | None = Query(default=None), service_name: str | None = Query(default=None), proposal_id: str | None = Query(default=None), experiment_id: str | None = Query(default=None), status: str | None = Query(default=None), limit: int = Query(default=50, ge=0, le=500)) -> dict:
    try:
        items = get_report_registry().list_reports(workspace_id, service_name, proposal_id, experiment_id, status, limit)
        return {"reports": [item.to_dict() for item in items], "count": len(items)}
    except Exception as exc:
        return {"status": "error", "error_type": type(exc).__name__, "error": "report_listing_failed", "reports": []}


@router.get("/reports/{report_id}")
def report(report_id: str) -> dict:
    try:
        item = get_report_registry().get(report_id)
        return {"status": "not_found", "report_id": report_id} if item is None else {"report": item.to_dict()}
    except Exception as exc:
        return {"status": "error", "error_type": type(exc).__name__, "error": "report_lookup_failed"}


@router.post("/portfolio-report")
def portfolio_report(payload: dict[str, Any] = Body(default_factory=dict)) -> dict:
    try:
        workspace_id = str(payload.get("workspace_id", "default"))
        limit = max(0, min(int(payload.get("limit", 50)), 500))
        reports = get_report_registry().list_reports(workspace_id=workspace_id, limit=limit)
        portfolio = build_portfolio_report(workspace_id, reports, payload.get("title"), payload.get("limit_recommendations", 10))
        get_report_registry().register_portfolio_report(portfolio)
        obsidian = sync_portfolio_report_note(portfolio)
        return {"portfolio_report_id": portfolio.portfolio_report_id, "portfolio_report": portfolio.to_dict(), "obsidian": obsidian}
    except Exception as exc:
        return {"status": "error", "error_type": type(exc).__name__, "error": "portfolio_report_failed"}


@router.get("/portfolio-reports")
def portfolio_reports(workspace_id: str | None = Query(default=None), limit: int = Query(default=50, ge=0, le=500)) -> dict:
    try:
        items = get_report_registry().list_portfolio_reports(workspace_id, limit)
        return {"portfolio_reports": [item.to_dict() for item in items], "count": len(items)}
    except Exception as exc:
        return {"status": "error", "error_type": type(exc).__name__, "error": "portfolio_report_listing_failed", "portfolio_reports": []}


@router.get("/portfolio-reports/{portfolio_report_id}")
def portfolio_report_detail(portfolio_report_id: str) -> dict:
    try:
        item = get_report_registry().get_portfolio_report(portfolio_report_id)
        return {"status": "not_found", "portfolio_report_id": portfolio_report_id} if item is None else {"portfolio_report": item.to_dict()}
    except Exception as exc:
        return {"status": "error", "error_type": type(exc).__name__, "error": "portfolio_report_lookup_failed"}


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
