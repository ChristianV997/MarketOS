"""services.product_research.report — render_product_audit_markdown."""
from __future__ import annotations

from services.reporting.render import render_markdown_report

from .schemas import ProductAuditResult
from .dossiers import CategoryDossier

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


def render_category_dossier_markdown(dossier: CategoryDossier) -> str:
    """Render the human-review artifact for a research-only category run."""
    products = [{
        "id": item.product_id,
        "name": item.name,
        "recommendation": item.recommendation,
        "score": item.score,
        "supplier_count": len(item.supplier_offers),
        "landed_costs": sorted({offer.landed_cost for offer in item.supplier_offers if offer.landed_cost is not None}),
    } for item in dossier.products]
    sections = [
        {"heading": "Research status", "body": {"category": dossier.category, "category_id": dossier.category_id,
                                                   "status": dossier.status, "generated_at": dossier.generated_at}},
        {"heading": "Top product candidates", "body": products},
        {"heading": "Portfolio recommendation", "body": dossier.portfolio},
        {"heading": "Scenarios", "body": dossier.scenarios},
        {"heading": "Tipping-point score", "body": dossier.tipping_point},
        {"heading": "Audience and evidence", "body": dossier.audience_summary},
        {"heading": "Source health", "body": dossier.source_health},
        {"heading": "Approval boundary", "body": {"message": "No brand, inventory, page, account, ad, or order was created by this report."}},
    ]
    return render_markdown_report("MarketOS Category Research Dossier", sections, dry_run=True,
                                  generated_at=dossier.generated_at)
