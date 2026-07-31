"""marketos.cli — terminal entrypoint for MarketOS service modules.

    python -m marketos.cli services product-audit --product NAME [...]
    python -m marketos.cli services unit-economics --product NAME --cost C --price P [...]
    python -m marketos.cli services sales-bot-sim --vertical car_sales [--message "..." ...]

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
        print(json.dumps(result.to_dict(), indent=2, default=str))
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


_DEMO_LEAD_MESSAGES = [
    "Hi, I'm interested and looking to get started soon",
    "My budget is around $2,000 and I'm located nearby",
]


def _cmd_sales_bot_sim(args: argparse.Namespace) -> int:
    from services.sales_automation.report import render_sales_bot_setup_plan_markdown
    from services.sales_automation.simulate import run_sales_bot_simulation

    workspace = _resolve_workspace(args.workspace)
    messages = args.message or list(_DEMO_LEAD_MESSAGES)
    session, handoff, flow, _envelope = run_sales_bot_simulation(args.vertical, messages, workspace=workspace)

    if args.json:
        print(json.dumps({
            "session": session.to_dict(), "handoff": handoff.to_dict(), "qualification_flow": flow,
        }, indent=2, default=str))
    else:
        print(render_sales_bot_setup_plan_markdown(session, handoff, flow))
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

    sales_bot = services_sub.add_parser("sales-bot-sim", help="Simulate a lead-qualification chat conversation (local only, no real messaging)")
    sales_bot.add_argument("--vertical", required=True)
    sales_bot.add_argument("--message", action="append", help="A scripted lead message; repeat for a multi-turn conversation. Defaults to a short demo script if omitted.")
    sales_bot.add_argument("--workspace", default=None)
    sales_bot.add_argument("--json", action="store_true")
    sales_bot.set_defaults(func=_cmd_sales_bot_sim)

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
