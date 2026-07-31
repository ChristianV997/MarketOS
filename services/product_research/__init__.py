"""services.product_research — turn discovery + validation into a sellable
product/category opportunity audit."""
from .audit import run_product_audit
from .report import render_product_audit_markdown
from .schemas import ProductAuditResult

__all__ = ["run_product_audit", "render_product_audit_markdown", "ProductAuditResult"]
