"""services.customer_intelligence.report — render_customer_intelligence_markdown."""
from __future__ import annotations

from services.reporting.render import render_markdown_report

from .sprint import CustomerIntelligenceSprint

TITLE = "MarketOS Customer Acquisition Intelligence Sprint"


def render_customer_intelligence_markdown(result: CustomerIntelligenceSprint) -> str:
    sections = [
        {"heading": "Summary", "body": {"business_type": result.business_type, "vertical": result.vertical}},
        {"heading": "Ideal Customer Profile", "body": result.icp},
        {"heading": "Customer Segments", "body": result.segments},
        {"heading": "Lead Strategy", "body": result.lead_strategy},
        {"heading": "Publicity Strategy", "body": result.publicity_strategy},
    ]
    if result.vertical_playbook:
        sections.append({"heading": f"Vertical Playbook: {result.vertical}", "body": result.vertical_playbook})
    return render_markdown_report(TITLE, sections, dry_run=result.dry_run, generated_at=result.generated_at)
