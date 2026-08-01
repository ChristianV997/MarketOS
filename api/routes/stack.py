"""api.routes.stack — the lightweight, non-billable Stack Planner endpoint.

Mirrors marketos.cli's `stack recommend` subcommand: calls
backend.stack_planner.planner.recommend_stack directly, with no
CommercialRunEnvelope/audit log — a distinct, lighter tool from the
sellable, audited `POST /api/services/profit-stack-advisor`
(api.routes.services.profit_stack_advisor).
"""
from __future__ import annotations

from fastapi import APIRouter

from services.reporting import json_safe

router = APIRouter(prefix="/api/stack")


def _resolve_workspace(name: str | None):
    from backend.workspaces.client_workspace import ClientWorkspace
    from backend.workspaces.registry import get_workspace_registry

    if not name:
        return ClientWorkspace(name="api-default", workspace_type="internal")
    registry = get_workspace_registry()
    ws = registry.by_name(name)
    if ws is None:
        ws = ClientWorkspace(name=name, workspace_type="internal")
        registry.register(ws)
    return ws


@router.post("/recommend")
def recommend(
    business_model: str = "own_ecommerce",
    target_geo: str = "MX",
    expected_monthly_revenue_usd: float = 5000.0,
    expected_monthly_orders: float = 0.0,
    margin_sensitivity: str = "standard",
    is_white_labeled_client_facing: bool = False,
    postiz_legal_approval: bool = False,
    category: str = "general",
    supplier_cost: float = 0.0,
    retail_price: float = 0.0,
    workspace: str | None = None,
):
    """Never raises: backend.stack_planner.recommend_stack is already
    never-raise; this route wraps it anyway for the same structured-error
    convention as every other route in this API."""
    from backend.stack_planner.planner import recommend_stack
    from backend.stack_planner.schemas import BusinessStackRequest
    try:
        request = BusinessStackRequest(
            business_model=business_model, target_geo=target_geo,
            expected_monthly_revenue_usd=expected_monthly_revenue_usd, expected_monthly_orders=expected_monthly_orders,
            margin_sensitivity=margin_sensitivity, is_white_labeled_client_facing=is_white_labeled_client_facing,
            postiz_legal_approval=postiz_legal_approval, category=category,
            supplier_cost=supplier_cost, retail_price=retail_price, workspace=_resolve_workspace(workspace),
        )
        result = recommend_stack(request)
        return json_safe({"result": result.to_dict()})
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
