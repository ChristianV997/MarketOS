"""services.ecommerce_operator.report — render_commerce_experiment_markdown."""
from __future__ import annotations

from services.reporting.render import render_markdown_report

from .schemas import ContributionProfitResult, LaunchReadiness, ScaleDecision

TITLE = "MarketOS E-commerce Validation Experiment"


def render_commerce_experiment_markdown(
    product_name: str,
    *,
    readiness: LaunchReadiness | None = None,
    contribution: ContributionProfitResult | None = None,
    decision: ScaleDecision | None = None,
    dry_run: bool = True,
) -> str:
    sections = [{"heading": "Product", "body": {"product_name": product_name}}]
    if readiness is not None:
        sections.append({"heading": "Launch Readiness", "body": readiness.to_dict()})
    if contribution is not None:
        sections.append({"heading": "Contribution Profit", "body": contribution.to_dict()})
    if decision is not None:
        sections.append({"heading": "Kill/Scale Decision", "body": decision.to_dict()})
    return render_markdown_report(TITLE, sections, dry_run=dry_run)
