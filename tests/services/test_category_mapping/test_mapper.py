"""Tests for services.category_mapping.mapper.build_category_mapping_evidence."""
from __future__ import annotations

from services.category_mapping.mapper import build_category_mapping_evidence
from services.category_mapping.schemas import CategoryMappingEvidence
from services.category_mapping.taxonomy_loader import parse_taxonomy_text

FIXTURE_TEXT = """
gid://shopify/TaxonomyCategory/ap    : Animals & Pet Supplies
gid://shopify/TaxonomyCategory/ap-1  : Animals & Pet Supplies > Live Animals
gid://shopify/TaxonomyCategory/ap-2  : Animals & Pet Supplies > Pet Supplies
gid://shopify/TaxonomyCategory/ap-2-1: Animals & Pet Supplies > Pet Supplies > Bird Supplies
gid://shopify/TaxonomyCategory/ap-2-2: Animals & Pet Supplies > Pet Supplies > Cat Supplies
"""


def _fixture_taxonomy():
    return parse_taxonomy_text(FIXTURE_TEXT)


class TestExactAndUnmappedCategories:
    def test_exact_case_insensitive_name_match_gets_confidence_one(self):
        evidence = build_category_mapping_evidence("bird supplies", taxonomy=_fixture_taxonomy())
        assert evidence.status == "mapped"
        assert evidence.candidates[0].code == "ap-2-1"
        assert evidence.candidates[0].match_basis == "exact_name"
        assert evidence.candidates[0].confidence == 1.0

    def test_unknown_category_with_no_token_overlap_is_reported_unmapped(self):
        evidence = build_category_mapping_evidence("Quantum Flux Capacitor", taxonomy=_fixture_taxonomy())
        assert evidence.status == "unmapped"
        assert evidence.candidates == ()

    def test_empty_input_is_unmapped_not_a_crash_or_a_default_category(self):
        evidence = build_category_mapping_evidence("", taxonomy=_fixture_taxonomy())
        assert evidence.status == "unmapped"
        assert evidence.candidates == ()

    def test_none_like_missing_input_is_unmapped(self):
        evidence = build_category_mapping_evidence(None, taxonomy=_fixture_taxonomy())  # type: ignore[arg-type]
        assert evidence.status == "unmapped"
        assert evidence.input_category == ""


class TestTokenOverlapMatching:
    def test_partial_token_overlap_produces_a_bounded_non_exact_candidate(self):
        evidence = build_category_mapping_evidence("Pet Supplies Bird", taxonomy=_fixture_taxonomy())
        assert evidence.status == "mapped"
        codes = {c.code for c in evidence.candidates}
        assert "ap-2-1" in codes  # "Bird Supplies" shares "supplies"/"bird" tokens
        for candidate in evidence.candidates:
            assert 0.0 < candidate.confidence <= 0.99
            assert candidate.match_basis in {"exact_name", "token_overlap"}

    def test_candidates_are_capped_and_sorted_deterministically(self):
        evidence = build_category_mapping_evidence("Supplies", taxonomy=_fixture_taxonomy())
        confidences = [c.confidence for c in evidence.candidates]
        assert confidences == sorted(confidences, reverse=True)
        assert len(evidence.candidates) <= 5


class TestDeterminism:
    def test_identical_input_and_taxonomy_produce_byte_identical_evidence(self):
        taxonomy = _fixture_taxonomy()
        first = build_category_mapping_evidence("Bird Supplies", taxonomy=taxonomy)
        second = build_category_mapping_evidence("Bird Supplies", taxonomy=taxonomy)
        assert first.to_dict() == second.to_dict()

    def test_reparsed_taxonomy_still_produces_identical_evidence(self):
        first = build_category_mapping_evidence("Bird Supplies", taxonomy=_fixture_taxonomy())
        second = build_category_mapping_evidence("Bird Supplies", taxonomy=_fixture_taxonomy())
        assert first.to_dict() == second.to_dict()

    def test_a_tied_overlap_score_breaks_ties_by_code_not_insertion_order(self):
        # ap-2-1 and ap-2-2 both share exactly the same overlap with "Supplies".
        evidence = build_category_mapping_evidence("Supplies", taxonomy=_fixture_taxonomy())
        tied = [c for c in evidence.candidates if c.name.endswith("Supplies") and c.code in {"ap-2-1", "ap-2-2"}]
        codes_in_order = [c.code for c in tied]
        assert codes_in_order == sorted(codes_in_order)


class TestEvidenceIsNotAnAuthority:
    def test_evidence_never_claims_decision_authority(self):
        evidence = build_category_mapping_evidence("Bird Supplies", taxonomy=_fixture_taxonomy())
        assert evidence.decision_authority == "none"
        assert evidence.human_review_required is True

    def test_evidence_carries_taxonomy_source_provenance(self):
        evidence = build_category_mapping_evidence("Bird Supplies", taxonomy=_fixture_taxonomy())
        source = evidence.taxonomy_source
        assert source["repository_url"] == "https://github.com/Shopify/product-taxonomy"
        assert source["version_tag"] == "v2026-08"
        assert source["license"] == "MIT"

    def test_to_dict_round_trips_every_field(self):
        evidence = build_category_mapping_evidence("Bird Supplies", taxonomy=_fixture_taxonomy())
        as_dict = evidence.to_dict()
        assert as_dict["status"] == "mapped"
        assert as_dict["candidates"][0]["code"] == "ap-2-1"
        assert isinstance(as_dict["taxonomy_source"], dict)


class TestEvidenceInvariants:
    def test_construction_rejects_unmapped_evidence_carrying_candidates(self):
        import pytest
        from services.category_mapping.schemas import CategoryMappingCandidate, CategoryTaxonomyError

        bogus_candidate = CategoryMappingCandidate(
            code="x", gid="gid://x", name="X", full_path="X", match_basis="exact_name", confidence=1.0
        )
        with pytest.raises(CategoryTaxonomyError):
            CategoryMappingEvidence(
                input_category="x", normalized_input="x", status="unmapped", candidates=(bogus_candidate,)
            )

    def test_construction_rejects_mapped_evidence_with_no_candidates(self):
        import pytest
        from services.category_mapping.schemas import CategoryTaxonomyError

        with pytest.raises(CategoryTaxonomyError):
            CategoryMappingEvidence(input_category="x", normalized_input="x", status="mapped", candidates=())
