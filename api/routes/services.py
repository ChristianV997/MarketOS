"""api.routes.services — thin route wrappers over services.product_research
and services.unit_economics (Phase 7: SaaS-lite readiness). Only these two
modules are exposed today — they're pure/stateless (no live spend, no
external side effects) and match the "service functions first, route
wrappers second" order this repo's task spec calls for. The remaining
service modules (ecommerce_operator, creative_growth, customer_intelligence,
digital_products, sales_automation) are reachable via services.* imports
and marketos.cli today; a full API surface for all of them, plus real
auth/billing, is future SaaS-lite work — see docs/SERVICE_MODULES.md.
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/services")


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


@router.post("/product-audit")
def product_audit(product: str, category: str = "general", price: float | None = None, workspace: str | None = None):
    """Product & category opportunity audit. Never raises — the underlying
    service function is itself never-raise; any unexpected failure here
    surfaces as a structured error dict, not a 500 with a stack trace."""
    from services.product_research.audit import run_product_audit
    try:
        result, envelope = run_product_audit(
            product, category=category, retail_price=price, workspace=_resolve_workspace(workspace),
        )
        return {"result": result.to_dict(), "experiment_id": envelope.experiment_id}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@router.post("/unit-economics")
def unit_economics(
    product: str, cost: float, price: float, shipping: float = 0.0,
    category: str = "general", geo: str | None = None, workspace: str | None = None,
):
    """Unit economics diagnostic. Never raises for the same reason as
    product_audit above."""
    from services.unit_economics.analyzer import run_unit_economics
    try:
        result, envelope = run_unit_economics(
            product, supplier_cost=cost, retail_price=price, shipping_cost=shipping,
            category=category, geo=geo, workspace=_resolve_workspace(workspace),
        )
        return {"result": result.to_dict(), "experiment_id": envelope.experiment_id}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
