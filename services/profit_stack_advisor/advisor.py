"""services.profit_stack_advisor.advisor — run_profit_stack_advisor, the
paid-service entrypoint wrapping backend.stack_planner.recommend_stack. No
new stack-decision logic lives here — this module only wraps the planner
in the standard CommercialRunEnvelope/report/status shape every service
module uses (see services.unit_economics.analyzer for the pattern this
mirrors).
"""
from __future__ import annotations

import logging

from backend.experiments.audit_log import log_transition
from backend.experiments.envelope import CommercialRunEnvelope
from backend.experiments.registry import get_experiment_registry
from backend.stack_planner.schemas import BusinessStackRequest
from backend.workspaces.artifact_store import ArtifactStore
from backend.workspaces.client_workspace import ClientWorkspace

from .schemas import ProfitStackAdvisorResult

_log = logging.getLogger(__name__)

SERVICE_NAME = "profit_stack_advisor"


def _default_workspace() -> ClientWorkspace:
    return ClientWorkspace(name="ephemeral", workspace_type="internal")


def run_profit_stack_advisor(
    business_name: str,
    *,
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
    workspace: ClientWorkspace | None = None,
) -> tuple[ProfitStackAdvisorResult, CommercialRunEnvelope]:
    """Never raises: backend.stack_planner.recommend_stack is already
    never-raise; this function wraps it anyway so a surprise failure
    degrades to a partial result instead of aborting."""
    workspace = workspace or _default_workspace()
    registry = get_experiment_registry()
    store = ArtifactStore()

    envelope = CommercialRunEnvelope(
        service_name=SERVICE_NAME,
        workspace_id=workspace.workspace_id,
        mode="dry_run" if workspace.dry_run_default else workspace.mode,
        inputs={
            "business_name": business_name, "business_model": business_model, "target_geo": target_geo,
            "expected_monthly_revenue": expected_monthly_revenue, "expected_monthly_orders": expected_monthly_orders,
            "margin_sensitivity": margin_sensitivity, "is_white_labeled_client_facing": is_white_labeled_client_facing,
            "postiz_legal_approval": postiz_legal_approval, "category": category,
            "supplier_cost": supplier_cost, "retail_price": retail_price,
        },
    )
    registry.register(envelope)
    log_transition(envelope, "experiment_created")
    envelope.mark_running()
    log_transition(envelope, "experiment_running")

    recommendation: dict = {}
    cost_comparison: dict | None = None
    try:
        from backend.stack_planner.planner import recommend_stack

        request = BusinessStackRequest(
            business_model=business_model, target_geo=target_geo,
            expected_monthly_revenue_usd=expected_monthly_revenue, expected_monthly_orders=expected_monthly_orders,
            margin_sensitivity=margin_sensitivity, is_white_labeled_client_facing=is_white_labeled_client_facing,
            postiz_legal_approval=postiz_legal_approval, category=category,
            supplier_cost=supplier_cost, retail_price=retail_price, workspace=workspace,
        )
        rec = recommend_stack(request)
        recommendation = rec.to_dict()

        from backend.stack_planner.strategies import is_lead_gen_strategy

        if rec.status == "recommended" and margin_sensitivity != "premium_brand" and not is_lead_gen_strategy(rec.strategy_id):
            # Show the client what the premium alternative would cost, so the
            # recommendation reads as a comparison rather than a bare answer.
            # Only meaningful for e-commerce strategies (checkout/payment
            # stack comparison) — lead-gen/agency strategies have no Shopify-
            # style alternative to compare against.
            from backend.costs.compare import compare_stacks

            premium_request = BusinessStackRequest(
                business_model="client_ecommerce_shopify_premium", target_geo=target_geo,
                expected_monthly_revenue_usd=expected_monthly_revenue, expected_monthly_orders=expected_monthly_orders,
                margin_sensitivity="premium_brand", is_white_labeled_client_facing=is_white_labeled_client_facing,
                postiz_legal_approval=postiz_legal_approval, category=category,
                supplier_cost=supplier_cost, retail_price=retail_price, workspace=workspace,
            )
            premium_rec = recommend_stack(premium_request)
            if premium_rec.status == "recommended":
                comparison = compare_stacks([rec.monthly_cost_estimate, premium_rec.monthly_cost_estimate])
                cost_comparison = comparison.to_dict()
    except Exception as exc:  # noqa: BLE001
        _log.warning("profit_stack_advisor_recommend_failed business=%s error=%s", business_name, exc)

    from services.status import commercial_status
    status = commercial_status(workspace=workspace)  # pure math, no external credentials/live data needed

    result = ProfitStackAdvisorResult(
        business_name=business_name,
        business_model=business_model,
        recommendation=recommendation,
        cost_comparison=cost_comparison,
        dry_run=workspace.dry_run_default,
        status=status,
    )

    try:
        from services.reporting import save_report_artifacts
        from .report import render_profit_stack_advisor_markdown
        save_report_artifacts(store, workspace.workspace_id, envelope.experiment_id,
                               render_profit_stack_advisor_markdown(result), result.to_dict())
    except Exception as exc:  # noqa: BLE001 — the JSON result below is the durable fallback
        _log.debug("profit_stack_advisor_report_save_failed error=%s", exc)
        store.save(workspace.workspace_id, envelope.experiment_id, "result.json", result.to_dict())

    envelope.mark_completed(result.to_dict())
    log_transition(envelope, "experiment_completed")

    return result, envelope
