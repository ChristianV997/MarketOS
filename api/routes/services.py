"""api.routes.services — thin route wrappers over services.product_research,
services.unit_economics, and services.ecommerce_operator (Phase 7: SaaS-lite
readiness; ecommerce_operator added in the consolidation phase once it had
ledger wiring). These three are exposed today — they're either pure/
stateless (product_research, unit_economics) or, for ecommerce_operator,
produce a decision/readiness verdict without executing anything live
itself (see docs/LIVE_MODE_SAFETY.md). The remaining service modules
(creative_growth, customer_intelligence, digital_products, sales_automation)
are reachable via services.* imports and marketos.cli today; a full API
surface for all of them, plus real auth/billing, is future SaaS-lite
work — see docs/SERVICE_MODULES.md.
"""
from __future__ import annotations

from typing import Any

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


@router.post("/ecommerce-operator")
def ecommerce_operator(
    product: str,
    category: str = "general",
    validation: dict[str, Any] | None = None,
    unit_economics: dict[str, Any] | None = None,
    supplier_assumptions: dict[str, Any] | None = None,
    budget_ceiling: float | None = None,
    kill_criteria: dict[str, Any] | None = None,
    attribution_method: str | None = None,
    roas: float = 0.0,
    proposed_scale_amount: float = 0.0,
    live_action: bool = False,
    workspace: str | None = None,
):
    """Launch readiness + ledger-derived contribution profit + kill/scale
    decision for one product, delegating to the same functions
    marketos.cli's `services ecommerce-operator` subcommand calls — one
    code path, not two. Never raises for the same reason as the routes
    above: this only produces a decision/readiness verdict (see
    docs/LIVE_MODE_SAFETY.md) and doesn't execute anything live itself."""
    from services.ecommerce_operator.experiment import create_commerce_experiment
    from services.ecommerce_operator.launch_guard import evaluate_launch_readiness
    from services.ecommerce_operator.contribution_profit import from_ledger
    from services.ecommerce_operator.scale_decision import make_kill_scale_decision

    try:
        ws = _resolve_workspace(workspace)
        envelope = create_commerce_experiment(
            product, validation=validation, unit_economics=unit_economics,
            supplier_assumptions=supplier_assumptions, budget_ceiling=budget_ceiling,
            kill_criteria=kill_criteria, attribution_method=attribution_method,
            category=category, workspace=ws,
        )
        readiness = evaluate_launch_readiness(
            envelope, workspace=ws, live_action_requested=live_action,
        )
        contribution = from_ledger(envelope)
        decision = make_kill_scale_decision(
            envelope, contribution, roas=roas, proposed_scale_amount=proposed_scale_amount,
        )
        return {
            "readiness": readiness.to_dict(),
            "contribution": contribution.to_dict(),
            "decision": decision.to_dict(),
            "experiment_id": envelope.experiment_id,
        }
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
