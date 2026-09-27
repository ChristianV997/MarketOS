"""services.category_mapping -- supplemental, offline category-mapping
evidence against a pinned, partial snapshot of the Shopify Product Taxonomy
(MIT-licensed; see ``data/shopify_product_taxonomy/README.md`` and
``THIRD_PARTY_NOTICES.md``).

This package produces evidence for human review only. It is not a ranker, a
supplier-proof authority, a live-validation signal, or a launch/decision
gate: ``CategoryMappingEvidence.decision_authority`` is always ``"none"`` and
``human_review_required`` is always ``True``. Public source retrieval occurred strictly
as an offline developer-time dataset curation step; the package executes with zero
runtime network access, makes no provider calls, reads no credentials, and never
mutates commerce, publication, ad, or ordering state. It composes with -- and does not
duplicate -- the existing ``evaluation.commerce.opportunity_synthesis``
three-pillar decision layer and the existing
``evaluation.trustos.client_workspace_isolation`` export boundary; neither
authority is reimplemented here.
"""
from .mapper import build_category_mapping_evidence
from .schemas import (
    CategoryMappingCandidate,
    CategoryMappingEvidence,
    CategoryTaxonomyError,
    TaxonomyCategory,
)
from .taxonomy_loader import TaxonomyIndex, default_taxonomy, load_taxonomy, parse_taxonomy_text

__all__ = [
    "build_category_mapping_evidence",
    "CategoryMappingCandidate",
    "CategoryMappingEvidence",
    "CategoryTaxonomyError",
    "TaxonomyCategory",
    "TaxonomyIndex",
    "default_taxonomy",
    "load_taxonomy",
    "parse_taxonomy_text",
]
