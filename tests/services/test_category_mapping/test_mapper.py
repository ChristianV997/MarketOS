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
        assert len(evidence.candidates) == 1
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
        assert evidence.status == "ambiguous"
        assert len(evidence.candidates) > 1
        codes = {c.code for c in evidence.candidates}
        assert "ap-2-1" in codes  # "Bird Supplies" shares "supplies"/"bird" tokens
        for candidate in evidence.candidates:
            assert 0.0 < candidate.confidence <= 0.99
            assert candidate.match_basis in {"exact_name", "token_overlap"}

    def test_candidates_are_capped_and_sorted_deterministically(self):
        evidence = build_category_mapping_evidence("Supplies", taxonomy=_fixture_taxonomy())
        assert evidence.status == "ambiguous"
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

    def test_exact_match_wins_over_weaker_token_overlap(self):
        evidence = build_category_mapping_evidence("Pet Supplies", taxonomy=_fixture_taxonomy())
        assert evidence.status == "mapped"
        assert [candidate.code for candidate in evidence.candidates] == ["ap-2"]

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

    def test_construction_rejects_mapped_evidence_with_multiple_candidates(self):
        import pytest
        from services.category_mapping.schemas import CategoryMappingCandidate, CategoryTaxonomyError

        candidate = CategoryMappingCandidate(
            code="x", gid="gid://x", name="X", full_path="X", match_basis="exact_name", confidence=1.0
        )
        with pytest.raises(CategoryTaxonomyError, match="exactly one candidate"):
            CategoryMappingEvidence(
                input_category="x",
                normalized_input="x",
                status="mapped",
                candidates=(candidate, candidate),
            )

    def test_construction_rejects_ambiguous_evidence_with_fewer_than_two_candidates(self):
        import pytest
        from services.category_mapping.schemas import CategoryMappingCandidate, CategoryTaxonomyError

        candidate = CategoryMappingCandidate(
            code="x", gid="gid://x", name="X", full_path="X", match_basis="exact_name", confidence=1.0
        )
        with pytest.raises(CategoryTaxonomyError, match="at least two candidates"):
            CategoryMappingEvidence(
                input_category="x",
                normalized_input="x",
                status="ambiguous",
                candidates=(candidate,),
            )

    def test_construction_rejects_human_review_required_override(self):
        import pytest
        from services.category_mapping.schemas import CategoryTaxonomyError

        with pytest.raises(CategoryTaxonomyError, match="human_review_required must be True"):
            CategoryMappingEvidence(
                input_category="x", normalized_input="x", status="unmapped", human_review_required=False
            )

        with pytest.raises(CategoryTaxonomyError, match="human_review_required must be True"):
            CategoryMappingEvidence(
                input_category="x", normalized_input="x", status="unmapped", human_review_required=None  # type: ignore[arg-type]
            )

    def test_construction_rejects_decision_authority_override(self):
        import pytest
        from services.category_mapping.schemas import CategoryTaxonomyError

        for bad_authority in ("launch_authority", "publish", "auto_approved", "scoring_authority", ""):
            with pytest.raises(CategoryTaxonomyError, match="decision_authority must be 'none'"):
                CategoryMappingEvidence(
                    input_category="x", normalized_input="x", status="unmapped", decision_authority=bad_authority
                )

    def test_replace_cannot_bypass_human_review_or_authority_invariants(self):
        from dataclasses import replace
        import pytest
        from services.category_mapping.schemas import CategoryTaxonomyError

        evidence = build_category_mapping_evidence("Bird Supplies", taxonomy=_fixture_taxonomy())

        with pytest.raises(CategoryTaxonomyError, match="human_review_required must be True"):
            replace(evidence, human_review_required=False)

        with pytest.raises(CategoryTaxonomyError, match="decision_authority must be 'none'"):
            replace(evidence, decision_authority="auto_approved")

    def test_taxonomy_source_is_genuinely_immutable(self):
        import pytest
        evidence = build_category_mapping_evidence("Bird Supplies", taxonomy=_fixture_taxonomy())

        with pytest.raises(TypeError):
            evidence.taxonomy_source["repository_url"] = "https://evil.example.com"

        with pytest.raises(AttributeError):
            evidence.taxonomy_source.clear()

        with pytest.raises(AttributeError):
            evidence.taxonomy_source.pop("license")

        # Defensively copied on construction
        mutable_dict = {"custom_key": "custom_val"}
        custom_evidence = CategoryMappingEvidence(
            input_category="x",
            normalized_input="x",
            status="unmapped",
            taxonomy_source=mutable_dict,
        )
        mutable_dict["custom_key"] = "mutated"
        assert custom_evidence.taxonomy_source["custom_key"] == "custom_val"
        with pytest.raises(TypeError):
            custom_evidence.taxonomy_source["custom_key"] = "hacked"

    def test_candidates_defensively_converted_to_immutable_tuple(self):
        from services.category_mapping.schemas import CategoryMappingCandidate

        cand = CategoryMappingCandidate(
            code="ap", gid="gid://shopify/TaxonomyCategory/ap", name="Animals", full_path="Animals",
            match_basis="exact_name", confidence=1.0,
        )
        cand_list = [cand]
        evidence = CategoryMappingEvidence(
            input_category="Animals",
            normalized_input="animals",
            status="mapped",
            candidates=cand_list,  # type: ignore[arg-type]
        )
        assert isinstance(evidence.candidates, tuple)
        cand_list.clear()
        assert len(evidence.candidates) == 1
