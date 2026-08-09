"""marketos.cli — terminal entrypoint for MarketOS service modules.

    python -m marketos.cli services product-audit --product NAME [...]
    python -m marketos.cli services unit-economics --product NAME --cost C --price P [...]
    python -m marketos.cli services ecommerce-operator --product NAME --roas R [...]
    python -m marketos.cli services creative-growth --product NAME [...]
    python -m marketos.cli services customer-intelligence --business-type TYPE [...]
    python -m marketos.cli services digital-product --offer-name NAME [...]
    python -m marketos.cli services sales-bot-sim --vertical car_sales [--message "..." ...] [--attempt-real-handoff]
    python -m marketos.cli services profit-stack-advisor --business-name NAME --business-model own_ecommerce [...]
    python -m marketos.cli stack recommend --business-model own_ecommerce --target-geo MX [...]

Dispatches straight to each service module's run_*/simulate function, which
are already never-raise; this module's own try/except at main() is the one
place allowed to be a normal exception boundary, since it isn't the money
path itself.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any


def _resolve_workspace(name: str | None):
    from backend.workspaces.client_workspace import ClientWorkspace
    from backend.workspaces.registry import get_workspace_registry

    if not name:
        return ClientWorkspace(name="cli-default", workspace_type="internal")
    registry = get_workspace_registry()
    ws = registry.by_name(name)
    if ws is None:
        ws = ClientWorkspace(name=name, workspace_type="internal")
        registry.register(ws)
    return ws


def _print_result(result: Any, markdown: str, *, as_json: bool) -> None:
    if as_json:
        from services.reporting import json_safe
        print(json.dumps(json_safe(result.to_dict()), indent=2, default=str))
    else:
        print(markdown)


def _cmd_product_audit(args: argparse.Namespace) -> int:
    from services.product_research.audit import run_product_audit
    from services.product_research.report import render_product_audit_markdown

    workspace = _resolve_workspace(args.workspace)
    result, _envelope = run_product_audit(
        args.product, category=args.category, retail_price=args.price, workspace=workspace,
    )
    _print_result(result, render_product_audit_markdown(result), as_json=args.json)
    return 0


def _cmd_unit_economics(args: argparse.Namespace) -> int:
    from services.unit_economics.analyzer import run_unit_economics
    from services.unit_economics.report import render_unit_economics_markdown

    workspace = _resolve_workspace(args.workspace)
    result, _envelope = run_unit_economics(
        args.product, supplier_cost=args.cost, retail_price=args.price,
        shipping_cost=args.shipping, category=args.category, geo=args.geo, workspace=workspace,
    )
    _print_result(result, render_unit_economics_markdown(result), as_json=args.json)
    return 0


def _cmd_ecommerce_operator(args: argparse.Namespace) -> int:
    from services.ecommerce_operator.experiment import create_commerce_experiment
    from services.ecommerce_operator.launch_guard import evaluate_launch_readiness
    from services.ecommerce_operator.contribution_profit import from_ledger
    from services.ecommerce_operator.scale_decision import make_kill_scale_decision
    from services.ecommerce_operator.report import render_commerce_experiment_markdown

    def _parse_json(raw: str | None) -> dict | None:
        return json.loads(raw) if raw else None

    workspace = _resolve_workspace(args.workspace)
    envelope = create_commerce_experiment(
        args.product,
        validation=_parse_json(args.validation_json),
        unit_economics=_parse_json(args.unit_economics_json),
        supplier_assumptions=_parse_json(args.supplier_assumptions_json),
        budget_ceiling=args.budget_ceiling,
        kill_criteria=_parse_json(args.kill_criteria_json),
        attribution_method=args.attribution_method,
        category=args.category,
        workspace=workspace,
    )
    readiness = evaluate_launch_readiness(
        envelope, workspace=workspace, live_action_requested=args.live_action,
    )
    contribution = from_ledger(envelope)
    decision = make_kill_scale_decision(
        envelope, contribution, roas=args.roas, proposed_scale_amount=args.proposed_scale_amount,
    )

    if args.json:
        from services.reporting import json_safe
        print(json.dumps(json_safe({
            "readiness": readiness.to_dict(),
            "contribution": contribution.to_dict(),
            "decision": decision.to_dict(),
            "experiment_id": envelope.experiment_id,
        }), indent=2, default=str))
    else:
        print(render_commerce_experiment_markdown(
            args.product, readiness=readiness, contribution=contribution, decision=decision,
            dry_run=workspace.dry_run_default,
        ))
    return 0


def _cmd_creative_growth(args: argparse.Namespace) -> int:
    from services.creative_growth.plan import build_creative_growth_plan
    from services.creative_growth.report import render_creative_growth_markdown

    workspace = _resolve_workspace(args.workspace)
    result, _envelope = build_creative_growth_plan(
        args.product, category=args.category, workspace=workspace,
    )
    _print_result(result, render_creative_growth_markdown(result), as_json=args.json)
    return 0


def _cmd_customer_intelligence(args: argparse.Namespace) -> int:
    from services.customer_intelligence.sprint import build_customer_intelligence_sprint
    from services.customer_intelligence.report import render_customer_intelligence_markdown

    workspace = _resolve_workspace(args.workspace)
    result, _envelope = build_customer_intelligence_sprint(
        args.business_type, vertical=args.vertical, target_geo=args.target_geo,
        category=args.category, workspace=workspace,
    )
    _print_result(result, render_customer_intelligence_markdown(result), as_json=args.json)
    return 0


def _cmd_digital_product(args: argparse.Namespace) -> int:
    from services.digital_products.plan import build_digital_product_plan
    from services.digital_products.report import render_digital_product_markdown

    workspace = _resolve_workspace(args.workspace)
    result, _envelope = build_digital_product_plan(
        args.offer_name, product_type=args.product_type, target_customer=args.target_customer,
        transformation_promised=args.transformation, price=args.price,
        target_buyers=args.target_buyers, has_existing_audience=args.has_existing_audience,
        workspace=workspace,
    )
    _print_result(result, render_digital_product_markdown(result), as_json=args.json)
    return 0


_DEMO_LEAD_MESSAGES = [
    "Hi, I'm interested and looking to get started soon",
    "My budget is around $2,000 and I'm located nearby",
]


def _cmd_sales_bot_sim(args: argparse.Namespace) -> int:
    from services.sales_automation.report import render_sales_bot_setup_plan_markdown
    from services.sales_automation.simulate import run_sales_bot_simulation

    workspace = _resolve_workspace(args.workspace)
    messages = args.message or list(_DEMO_LEAD_MESSAGES)
    session, handoff, flow, envelope = run_sales_bot_simulation(
        args.vertical, messages, workspace=workspace,
        attempt_real_handoff=args.attempt_real_handoff,
    )

    if args.json:
        from services.reporting import json_safe
        print(json.dumps(json_safe({
            "session": session.to_dict(), "handoff": handoff.to_dict(), "qualification_flow": flow,
            "real_handoff": envelope.outputs.get("real_handoff"),
            "commercial_status": envelope.outputs.get("commercial_status"),
        }), indent=2, default=str))
    else:
        print(render_sales_bot_setup_plan_markdown(session, handoff, flow))
    return 0


def _add_stack_request_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--business-model", default="own_ecommerce", help="e.g. own_ecommerce, client_ecommerce, marketos_owned_stack")
    parser.add_argument("--target-geo", default="MX")
    parser.add_argument("--expected-monthly-revenue", type=float, default=5000.0)
    parser.add_argument("--expected-monthly-orders", type=float, default=0.0)
    parser.add_argument("--margin-sensitivity", default="standard", help="low_cost_validation|standard|premium_brand")
    parser.add_argument("--white-labeled-client-facing", action="store_true")
    parser.add_argument("--postiz-legal-approval", action="store_true")
    parser.add_argument("--category", default="general")
    parser.add_argument("--supplier-cost", type=float, default=0.0)
    parser.add_argument("--retail-price", type=float, default=0.0)
    parser.add_argument("--workspace", default=None)
    parser.add_argument("--json", action="store_true")


def _cmd_profit_stack_advisor(args: argparse.Namespace) -> int:
    from services.profit_stack_advisor.advisor import run_profit_stack_advisor
    from services.profit_stack_advisor.report import render_profit_stack_advisor_markdown

    workspace = _resolve_workspace(args.workspace)
    result, _envelope = run_profit_stack_advisor(
        args.business_name, business_model=args.business_model, target_geo=args.target_geo,
        expected_monthly_revenue=args.expected_monthly_revenue, expected_monthly_orders=args.expected_monthly_orders,
        margin_sensitivity=args.margin_sensitivity, is_white_labeled_client_facing=args.white_labeled_client_facing,
        postiz_legal_approval=args.postiz_legal_approval, category=args.category,
        supplier_cost=args.supplier_cost, retail_price=args.retail_price, workspace=workspace,
    )
    _print_result(result, render_profit_stack_advisor_markdown(result), as_json=args.json)
    return 0


def _cmd_stack_recommend(args: argparse.Namespace) -> int:
    """Lighter, non-billable planning utility — no CommercialRunEnvelope/audit
    log, unlike the sellable `services profit-stack-advisor`."""
    from backend.stack_planner.planner import recommend_stack
    from backend.stack_planner.schemas import BusinessStackRequest

    workspace = _resolve_workspace(args.workspace)
    request = BusinessStackRequest(
        business_model=args.business_model, target_geo=args.target_geo,
        expected_monthly_revenue_usd=args.expected_monthly_revenue, expected_monthly_orders=args.expected_monthly_orders,
        margin_sensitivity=args.margin_sensitivity, is_white_labeled_client_facing=args.white_labeled_client_facing,
        postiz_legal_approval=args.postiz_legal_approval, category=args.category,
        supplier_cost=args.supplier_cost, retail_price=args.retail_price, workspace=workspace,
    )
    result = recommend_stack(request)
    if args.json:
        from services.reporting import json_safe
        print(json.dumps(json_safe(result.to_dict()), indent=2, default=str))
    else:
        print(f"strategy: {result.strategy_id} ({result.status})")
        if result.commerce_provider_recommendation:
            print(f"commerce: {result.commerce_provider_recommendation.provider_id}")
        if result.payment_provider_recommendation:
            print(f"payment: {result.payment_provider_recommendation.provider_id}")
        for rec in result.automation_recommendations:
            print(f"automation: {rec.provider_id} blocked={rec.blocked} {rec.blocked_reason}")
        for warning in result.warnings:
            print(f"warning: {warning}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="marketos", description="MarketOS service modules CLI")
    top = parser.add_subparsers(dest="group", required=True)
    services = top.add_parser("services", help="Run a MarketOS service module")
    services_sub = services.add_subparsers(dest="command", required=True)

    audit = services_sub.add_parser("product-audit", help="Product & category opportunity audit")
    audit.add_argument("--product", required=True)
    audit.add_argument("--category", default="general")
    audit.add_argument("--price", type=float, default=None)
    audit.add_argument("--workspace", default=None)
    audit.add_argument("--json", action="store_true")
    audit.set_defaults(func=_cmd_product_audit)

    unit_econ = services_sub.add_parser("unit-economics", help="Unit economics diagnostic")
    unit_econ.add_argument("--product", required=True)
    unit_econ.add_argument("--cost", type=float, required=True)
    unit_econ.add_argument("--price", type=float, required=True)
    unit_econ.add_argument("--shipping", type=float, default=0.0)
    unit_econ.add_argument("--category", default="general")
    unit_econ.add_argument("--geo", default=None)
    unit_econ.add_argument("--workspace", default=None)
    unit_econ.add_argument("--json", action="store_true")
    unit_econ.set_defaults(func=_cmd_unit_economics)

    ecom = services_sub.add_parser("ecommerce-operator", help="Launch readiness + ledger-derived contribution profit + kill/scale decision")
    ecom.add_argument("--product", required=True)
    ecom.add_argument("--category", default="general")
    ecom.add_argument("--validation-json", default=None, help="JSON blob for the validation prerequisite")
    ecom.add_argument("--unit-economics-json", default=None, help="JSON blob for the unit_economics prerequisite")
    ecom.add_argument("--supplier-assumptions-json", default=None)
    ecom.add_argument("--budget-ceiling", type=float, default=None)
    ecom.add_argument("--kill-criteria-json", default=None, help='e.g. \'{"min_roas": 1.5}\'')
    ecom.add_argument("--attribution-method", default=None)
    ecom.add_argument("--roas", type=float, required=True)
    ecom.add_argument("--proposed-scale-amount", type=float, default=0.0)
    ecom.add_argument("--live-action", action="store_true", help="Request live-mode approval check (default: dry-run readiness only)")
    ecom.add_argument("--workspace", default=None)
    ecom.add_argument("--json", action="store_true")
    ecom.set_defaults(func=_cmd_ecommerce_operator)

    creative = services_sub.add_parser("creative-growth", help="Ad angles/hooks + fatigue analysis + next-batch recommendation")
    creative.add_argument("--product", required=True)
    creative.add_argument("--category", default="general")
    creative.add_argument("--workspace", default=None)
    creative.add_argument("--json", action="store_true")
    creative.set_defaults(func=_cmd_creative_growth)

    cust_intel = services_sub.add_parser("customer-intelligence", help="ICP, segments, lead strategy, publicity plan, vertical playbook")
    cust_intel.add_argument("--business-type", required=True)
    cust_intel.add_argument("--vertical", default=None, help="e.g. real_estate, car_sales, ecommerce_brand, clinic_wellness, home_services, coaching_consulting, luxury_products")
    cust_intel.add_argument("--target-geo", default="MX")
    cust_intel.add_argument("--category", default="general")
    cust_intel.add_argument("--workspace", default=None)
    cust_intel.add_argument("--json", action="store_true")
    cust_intel.set_defaults(func=_cmd_customer_intelligence)

    digital = services_sub.add_parser("digital-product", help="Offer/funnel/content-plan/validation/margin/launch checklist for a digital product")
    digital.add_argument("--offer-name", required=True)
    digital.add_argument("--product-type", default="playbook", help="template|playbook|course|cohort|ebook|paid_report|prompt_pack|calculator|dashboard_access|mentorship")
    digital.add_argument("--target-customer", default="")
    digital.add_argument("--transformation", default="", help="The transformation_promised text")
    digital.add_argument("--price", type=float, default=0.0)
    digital.add_argument("--target-buyers", type=int, default=10)
    digital.add_argument("--has-existing-audience", action="store_true")
    digital.add_argument("--workspace", default=None)
    digital.add_argument("--json", action="store_true")
    digital.set_defaults(func=_cmd_digital_product)

    sales_bot = services_sub.add_parser("sales-bot-sim", help="Simulate qualification; optionally stage a gated Chatwoot draft")
    sales_bot.add_argument("--vertical", required=True)
    sales_bot.add_argument("--message", action="append", help="A scripted lead message; repeat for a multi-turn conversation. Defaults to a short demo script if omitted.")
    sales_bot.add_argument("--workspace", default=None)
    sales_bot.add_argument("--attempt-real-handoff", action="store_true", help="Explicitly request the configured Chatwoot draft-only path")
    sales_bot.add_argument("--json", action="store_true")
    sales_bot.set_defaults(func=_cmd_sales_bot_sim)

    profit_stack = services_sub.add_parser("profit-stack-advisor", help="Cost-aware commerce/payment stack recommendation + margin/break-even report")
    profit_stack.add_argument("--business-name", required=True)
    _add_stack_request_args(profit_stack)
    profit_stack.set_defaults(func=_cmd_profit_stack_advisor)

    stack = top.add_parser("stack", help="Cost-aware business stack planning (backend.stack_planner)")
    stack_sub = stack.add_subparsers(dest="command", required=True)
    stack_recommend = stack_sub.add_parser("recommend", help="Recommend a commerce/payment/automation stack for a business model (non-billable utility)")
    _add_stack_request_args(stack_recommend)
    stack_recommend.set_defaults(func=_cmd_stack_recommend)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 2)

    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001 — CLI boundary; wrapped functions are never-raise already
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
