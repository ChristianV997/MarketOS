"""services.profit_stack_advisor.report — render_profit_stack_advisor_markdown."""
from __future__ import annotations

from services.reporting.render import render_markdown_report

from .schemas import ProfitStackAdvisorResult

TITLE = "MarketOS Profit Stack Advisor"


def render_profit_stack_advisor_markdown(result: ProfitStackAdvisorResult) -> str:
    sections = [
        {"heading": "Business", "body": {
            "business_name": result.business_name,
            "business_model": result.business_model,
            "status": result.status,
        }},
        {"heading": "Recommended Stack", "body": result.recommendation or {"status": "not computed"}},
        {"heading": "Cost Comparison", "body": result.cost_comparison or {"status": "not computed"}},
    ]
    return render_markdown_report(TITLE, sections, dry_run=result.dry_run, generated_at=result.generated_at)
