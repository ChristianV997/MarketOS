"""services.creative_growth.report — render_creative_growth_markdown."""
from __future__ import annotations

from services.reporting.render import render_markdown_report

from .schemas import CreativeGrowthPlan

TITLE = "MarketOS Creative Testing & UGC Growth System"


def render_creative_growth_markdown(plan: CreativeGrowthPlan) -> str:
    sections = [
        {"heading": "Summary", "body": {
            "product": plan.product_name,
            "category": plan.category,
            "hooks": plan.hooks,
            "angles": plan.angles,
        }},
        {"heading": "Hook x Angle Testing Matrix", "body": plan.hook_matrix},
        {"heading": "UGC Briefs", "body": plan.ugc_briefs},
        {"heading": "Content Calendar", "body": plan.content_calendar},
        {"heading": "Creative Fatigue Report", "body": plan.fatigue_report},
        {"heading": "Next Creative Batch Recommendation", "body": plan.next_batch_recommendation},
    ]
    return render_markdown_report(TITLE, sections, dry_run=plan.dry_run, generated_at=plan.generated_at)
