"""services.product_research.report — render_product_audit_markdown."""
from __future__ import annotations

from services.reporting.render import render_markdown_report

from .schemas import ProductAuditResult

TITLE = "MarketOS Product & Category Opportunity Audit"


def render_product_audit_markdown(result: ProductAuditResult) -> str:
    sections = [
        {"heading": "Summary", "body": {
            "product": result.product_name,
            "category": result.category,
            "recommendation": result.recommendation,
        }},
        {"heading": "Validation", "body": result.validation},
        {"heading": "Supplier", "body": result.supplier or {"status": "no supplier found"}},
        {"heading": "Pricing", "body": result.pricing},
        {"heading": "Discovery Context", "body": result.discovery},
        {"heading": "Data Provenance (real vs mock)", "body": result.data_provenance},
    ]
    return render_markdown_report(TITLE, sections, dry_run=result.dry_run, generated_at=result.generated_at)
