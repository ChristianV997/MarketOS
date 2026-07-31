"""api.routes.services — thin route wrappers over all 8 services.* modules.
Every route is pure/stateless, or (ecommerce_operator, sales_automation)
produces a decision/readiness verdict or a local simulation without
executing anything live itself (see docs/LIVE_MODE_SAFETY.md,
docs/SALES_AUTOMATION_MODULE.md). Real auth/billing/multi-tenant
onboarding is still future SaaS-lite work — see docs/SERVICE_MODULES.md.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from services.reporting import json_safe

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
        return json_safe({"result": result.to_dict(), "experiment_id": envelope.experiment_id})
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
        return json_safe({
            "readiness": readiness.to_dict(),
            "contribution": contribution.to_dict(),
            "decision": decision.to_dict(),
            "experiment_id": envelope.experiment_id,
        })
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
        return json_safe({"result": result.to_dict(), "experiment_id": envelope.experiment_id})
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@router.post("/creative-growth")
def creative_growth(product: str, category: str = "general", workspace: str | None = None):
    """Ad angles/hooks + fatigue analysis + next-batch recommendation. Never
    raises for the same reason as the routes above."""
    from services.creative_growth.plan import build_creative_growth_plan
    try:
        result, envelope = build_creative_growth_plan(
            product, category=category, workspace=_resolve_workspace(workspace),
        )
        return json_safe({"result": result.to_dict(), "experiment_id": envelope.experiment_id})
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@router.post("/customer-intelligence")
def customer_intelligence(
    business_type: str, vertical: str | None = None, target_geo: str = "MX",
    category: str = "general", workspace: str | None = None,
):
    """ICP, segments, lead strategy, publicity plan, vertical playbook. Never
    raises for the same reason as the routes above."""
    from services.customer_intelligence.sprint import build_customer_intelligence_sprint
    try:
        result, envelope = build_customer_intelligence_sprint(
            business_type, vertical=vertical, target_geo=target_geo,
            category=category, workspace=_resolve_workspace(workspace),
        )
        return json_safe({"result": result.to_dict(), "experiment_id": envelope.experiment_id})
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@router.post("/digital-product")
def digital_product(
    offer_name: str, product_type: str = "playbook", target_customer: str = "",
    transformation_promised: str = "", price: float = 0.0, target_buyers: int = 10,
    has_existing_audience: bool = False, workspace: str | None = None,
):
    """Offer/funnel/content-plan/validation/margin/launch checklist for a
    digital product. Never raises for the same reason as the routes above."""
    from services.digital_products.plan import build_digital_product_plan
    try:
        result, envelope = build_digital_product_plan(
            offer_name, product_type=product_type, target_customer=target_customer,
            transformation_promised=transformation_promised, price=price,
            target_buyers=target_buyers, has_existing_audience=has_existing_audience,
            workspace=_resolve_workspace(workspace),
        )
        return json_safe({"result": result.to_dict(), "experiment_id": envelope.experiment_id})
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@router.post("/sales-automation")
def sales_automation(
    vertical: str, messages: list[str] | None = None, workspace: str | None = None,
):
    """Simulate a lead-qualification chat conversation — local only, no real
    messaging (see docs/SALES_AUTOMATION_MODULE.md). Never raises for the
    same reason as the routes above."""
    from services.sales_automation.simulate import run_sales_bot_simulation
    try:
        scripted = messages or [
            "Hi, I'm interested and looking to get started soon",
            "My budget is around $2,000 and I'm located nearby",
        ]
        session, handoff, flow, envelope = run_sales_bot_simulation(
            vertical, scripted, workspace=_resolve_workspace(workspace),
        )
        return json_safe({
            "session": session.to_dict(), "handoff": handoff.to_dict(),
            "qualification_flow": flow, "experiment_id": envelope.experiment_id,
        })
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@router.post("/profit-stack-advisor")
def profit_stack_advisor(
    business_name: str,
    business_model: str = "own_ecommerce",
    target_geo: str = "MX",
    expected_monthly_revenue: float = 5000.0,
    expected_monthly_orders: float = 0.0,
    margin_sensitivity: str = "standard",
    is_white_labeled_client_facing: bool = False,
    postiz_legal_approval: bool = False,
    category: str = "general",
    supplier_cost: float = 0.0,
    retail_price: float = 0.0,
    workspace: str | None = None,
):
    """Cost-aware commerce/payment stack recommendation + margin/break-even
    report (backend.stack_planner + backend.costs). Never raises for the
    same reason as the routes above."""
    from services.profit_stack_advisor.advisor import run_profit_stack_advisor
    try:
        result, envelope = run_profit_stack_advisor(
            business_name, business_model=business_model, target_geo=target_geo,
            expected_monthly_revenue=expected_monthly_revenue, expected_monthly_orders=expected_monthly_orders,
            margin_sensitivity=margin_sensitivity, is_white_labeled_client_facing=is_white_labeled_client_facing,
            postiz_legal_approval=postiz_legal_approval, category=category,
            supplier_cost=supplier_cost, retail_price=retail_price, workspace=_resolve_workspace(workspace),
        )
        return json_safe({"result": result.to_dict(), "experiment_id": envelope.experiment_id})
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
