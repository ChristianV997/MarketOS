"""services.product_research — turn discovery + validation into a sellable
product/category opportunity audit."""
from .audit import run_product_audit
from .report import render_product_audit_markdown
from .report import render_category_dossier_markdown
from .schemas import ProductAuditResult
from .dossiers import ApprovalRequest, BrandProposal, CategoryDossier, EvidenceRecord, ProductDossier, SupplierEvidence
from .run import ResearchRunConfig, run_category_research

__all__ = ["run_product_audit", "render_product_audit_markdown", "render_category_dossier_markdown",
           "ProductAuditResult", "EvidenceRecord", "SupplierEvidence", "ProductDossier",
           "CategoryDossier", "BrandProposal", "ApprovalRequest", "ResearchRunConfig", "run_category_research"]
