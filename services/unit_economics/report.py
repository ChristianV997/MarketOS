"""services.unit_economics.report — render_unit_economics_markdown."""
from __future__ import annotations

from services.reporting.render import render_markdown_report

from .schemas import UnitEconomicsResult

TITLE = "MarketOS Unit Economics Diagnostic"


def render_unit_economics_markdown(result: UnitEconomicsResult) -> str:
    sections = [
        {"heading": "Summary", "body": {
            "product": result.product_name,
            "category": result.category,
            "verdict": result.verdict,
            "break_even_cac": result.break_even_cac,
            "required_roas": result.required_roas,
            "effective_cac": result.effective_cac,
        }},
        {"heading": "Base Margin", "body": result.base_margin},
        {"heading": "Geo-Adjusted Margin", "body": result.geo_margin or {"status": "not requested"}},
        {"heading": "LTV-Adjusted Margin", "body": result.ltv_adjusted_margin},
        {"heading": "Price Sensitivity Scenarios", "body": result.scenarios or {"status": "not computed"}},
    ]
    return render_markdown_report(TITLE, sections, dry_run=result.dry_run, generated_at=result.generated_at)
