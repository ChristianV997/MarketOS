"""services.category_mapping.schemas -- dataclasses for the Shopify Product
Taxonomy category-mapping evidence vertical.

Every dataclass here represents supplemental, offline evidence for a human
to review -- never a ranking, a supplier proof, a live validation, or a
launch/decision authority. ``CategoryMappingEvidence.decision_authority`` is
always ``"none"`` and ``human_review_required`` is always ``True``; nothing
in this module selects a category on a caller's behalf.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class CategoryTaxonomyError(ValueError):
    """Raised for malformed, duplicate, or structurally inconsistent taxonomy
    source records. The loader fails closed rather than silently dropping or
    guessing at a bad row."""


@dataclass(frozen=True)
class TaxonomyCategory:
    """One node of the pinned, partial Shopify Product Taxonomy snapshot."""

    code: str
    gid: str
    name: str
    full_path: str
    parent_code: str | None
    level: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "gid": self.gid,
            "name": self.name,
            "full_path": self.full_path,
            "parent_code": self.parent_code,
            "level": self.level,
        }


@dataclass(frozen=True)
class CategoryMappingCandidate:
    """One candidate taxonomy match for a caller-supplied free-text category.

    ``confidence`` is a bounded, deterministic evidence score derived from
    exact or token-overlap text matching -- not a model prediction, not a
    ranking signal, and never itself sufficient to select a category.
    """

    code: str
    gid: str
    name: str
    full_path: str
    match_basis: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "gid": self.gid,
            "name": self.name,
            "full_path": self.full_path,
            "match_basis": self.match_basis,
            "confidence": self.confidence,
        }


TAXONOMY_SOURCE_PROVENANCE: dict[str, Any] = {
    "repository_url": "https://github.com/Shopify/product-taxonomy",
    "version_tag": "v2026-08",
    "commit_sha": "2e9aa2e9b882383952c63d212add13eb80f46cf9",
    "upstream_version_file": "2026-08",
    "license": "MIT",
    "license_evidence_url": "https://github.com/Shopify/product-taxonomy/blob/v2026-08/LICENSE",
    "snapshot_levels_included": (1, 2, 3),
    "snapshot_path": "data/shopify_product_taxonomy/categories.v2026-08.partial.txt",
}


@dataclass(frozen=True)
class CategoryMappingEvidence:
    """Supplemental category-mapping evidence for one caller-supplied
    free-text category string, for human review only."""

    input_category: str
    normalized_input: str
    status: str  # "mapped" | "unmapped"
    candidates: tuple[CategoryMappingCandidate, ...] = ()
    taxonomy_source: dict[str, Any] = field(default_factory=lambda: dict(TAXONOMY_SOURCE_PROVENANCE))
    human_review_required: bool = True
    decision_authority: str = "none"

    def __post_init__(self) -> None:
        if self.status not in {"mapped", "unmapped"}:
            raise CategoryTaxonomyError(f"invalid category mapping status: {self.status!r}")
        if self.status == "unmapped" and self.candidates:
            raise CategoryTaxonomyError("unmapped evidence must not carry candidates")
        if self.status == "mapped" and not self.candidates:
            raise CategoryTaxonomyError("mapped evidence must carry at least one candidate")

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_category": self.input_category,
            "normalized_input": self.normalized_input,
            "status": self.status,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "taxonomy_source": dict(self.taxonomy_source),
            "human_review_required": self.human_review_required,
            "decision_authority": self.decision_authority,
        }
