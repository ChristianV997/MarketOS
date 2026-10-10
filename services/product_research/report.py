"""services.product_research.report — render_product_audit_markdown."""
from __future__ import annotations

from services.reporting.render import render_markdown_report

from .schemas import ProductAuditResult

TITLE = "MarketOS Product & Category Opportunity Audit"


def render_product_audit_markdown(result: ProductAuditResult) -> str:
    if result.category_mapping_evidence is None:
        category_mapping_body = {
            "status": "unavailable",
            "reason": "category mapping evidence was not generated",
            "interpretation": "No mapping result is available; this does not mean the category is unmapped.",
        }
    else:
        category_mapping_body = {
            "interpretation": (
                "Supplemental offline taxonomy evidence only; not live validation or supplier proof. "
                "Human review is required; this evidence has no decision authority."
            ),
            "evidence": result.category_mapping_evidence,
        }
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
        {
            "heading": "Supplemental Category-Mapping Evidence (offline; human review only)",
            "body": category_mapping_body,
        },
    ]
    return render_markdown_report(TITLE, sections, dry_run=result.dry_run, generated_at=result.generated_at)
