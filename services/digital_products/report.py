"""services.digital_products.report — render_digital_product_markdown."""
from __future__ import annotations

from services.reporting.render import render_markdown_report

from .schemas import DigitalProductPlan

TITLE = "MarketOS Digital Product Launch Plan"


def render_digital_product_markdown(plan: DigitalProductPlan) -> str:
    sections = [
        {"heading": "Offer", "body": plan.offer},
        {"heading": "Funnel", "body": plan.funnel},
        {"heading": "Content Plan", "body": plan.content_plan},
        {"heading": "Validation", "body": plan.validation},
        {"heading": "Launch Checklist", "body": plan.launch_checklist},
        {"heading": "Metrics to Track", "body": plan.metrics_to_track},
        {"heading": "Kill/Iterate/Scale Criteria", "body": plan.decision_criteria},
    ]
    return render_markdown_report(TITLE, sections, dry_run=plan.dry_run, generated_at=plan.generated_at)
