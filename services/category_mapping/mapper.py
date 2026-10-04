"""services.category_mapping.mapper -- build_category_mapping_evidence.

Deterministic, offline, pure-text matching of a caller-supplied free-text
product category against the pinned, partial Shopify Product Taxonomy
snapshot. This produces supplemental evidence for a human to review -- it
never selects, ranks against other candidates' commercial merit, or
authorizes anything. See ``docs/CATEGORY_MAPPING_EVIDENCE.md``.
"""
from __future__ import annotations

import re
from typing import Sequence

from .schemas import CategoryMappingCandidate, CategoryMappingEvidence
from .taxonomy_loader import TaxonomyIndex, default_taxonomy

_MAX_CANDIDATES = 5
_WORD_RE = re.compile(r"[a-z0-9]+")


def _normalize(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


def _tokens(text: str) -> frozenset[str]:
    # Words shorter than 3 characters ("up", "in", "of", ...) are excluded --
    # they produce incidental, low-signal overlaps (e.g. "Wind-Up Toys"
    # matching an unrelated "...Up..." phrase on the single token "up") that
    # would add noise rather than genuine evidence to a human review.
    return frozenset(word for word in _WORD_RE.findall(text.lower()) if len(word) >= 3)


def _token_overlap(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    intersection = a & b
    if not intersection:
        return 0.0
    union = a | b
    return len(intersection) / len(union)


def build_category_mapping_evidence(
    free_text_category: str,
    *,
    taxonomy: TaxonomyIndex | None = None,
) -> CategoryMappingEvidence:
    """Return supplemental category-mapping evidence for ``free_text_category``.

    ``free_text_category`` may be missing/empty -- that is treated the same
    as any other unmatched input (``status="unmapped"``), never coerced into
    a default category and never raising.
    """
    taxonomy = taxonomy if taxonomy is not None else default_taxonomy()
    normalized_input = _normalize(free_text_category)
    input_tokens = _tokens(normalized_input)

    exact_matches: list[CategoryMappingCandidate] = []
    overlap_matches: list[CategoryMappingCandidate] = []

    if normalized_input:
        for category in sorted(taxonomy, key=lambda item: item.code):
            normalized_name = _normalize(category.name)
            if normalized_name == normalized_input:
                exact_matches.append(
                    CategoryMappingCandidate(
                        code=category.code,
                        gid=category.gid,
                        name=category.name,
                        full_path=category.full_path,
                        match_basis="exact_name",
                        confidence=1.0,
                    )
                )
                continue
            overlap = _token_overlap(input_tokens, _tokens(category.name))
            if overlap > 0.0:
                overlap_matches.append(
                    CategoryMappingCandidate(
                        code=category.code,
                        gid=category.gid,
                        name=category.name,
                        full_path=category.full_path,
                        match_basis="token_overlap",
                        confidence=round(min(overlap, 0.99), 4),
                    )
                )

    # An exact name match is stronger evidence than fuzzy token overlap. Do
    # not append weaker alternatives to an otherwise unambiguous exact match:
    # that would make a clear mapping look ambiguous to downstream reviewers.
    if exact_matches:
        ordered = sorted(exact_matches, key=lambda c: c.code)
    else:
        ordered = sorted(overlap_matches, key=lambda c: (-c.confidence, c.code))
    candidates: Sequence[CategoryMappingCandidate] = tuple(ordered[:_MAX_CANDIDATES])

    if not candidates:
        return CategoryMappingEvidence(
            input_category=str(free_text_category or ""),
            normalized_input=normalized_input,
            status="unmapped",
            candidates=(),
            taxonomy_source=taxonomy.source_provenance,
        )

    # Only a single exact name match is "mapped". A lone token-overlap
    # candidate is partial-word evidence, not a mapping: it stays visible to
    # the reviewer but is never upgraded to "mapped".
    if len(candidates) > 1:
        status = "ambiguous"
    elif candidates[0].match_basis == "exact_name":
        status = "mapped"
    else:
        status = "weak_candidate"
    return CategoryMappingEvidence(
        input_category=str(free_text_category or ""),
        normalized_input=normalized_input,
        status=status,
        candidates=candidates,
        taxonomy_source=taxonomy.source_provenance,
    )
