"""Tests for services.category_mapping.taxonomy_loader.

Every test builds its taxonomy text in-memory (via parse_taxonomy_text) so
malformed/duplicate cases never touch the real bundled snapshot file.
"""
from __future__ import annotations

import pytest

from services.category_mapping.schemas import CategoryTaxonomyError
from services.category_mapping.taxonomy_loader import (
    default_taxonomy,
    load_taxonomy,
    parse_taxonomy_text,
)

VALID_TEXT = """
# header comment, ignored
# Format: {GID} : {Ancestor name} > ... > {Category name}

gid://shopify/TaxonomyCategory/ap    : Animals & Pet Supplies
gid://shopify/TaxonomyCategory/ap-1  : Animals & Pet Supplies > Live Animals
gid://shopify/TaxonomyCategory/ap-2  : Animals & Pet Supplies > Pet Supplies
gid://shopify/TaxonomyCategory/ap-2-1: Animals & Pet Supplies > Pet Supplies > Bird Supplies
"""


class TestParsingAndStableIds:
    def test_parses_all_data_rows_and_ignores_comments_and_blank_lines(self):
        index = parse_taxonomy_text(VALID_TEXT)
        assert len(index) == 4
        assert set(index.by_code) == {"ap", "ap-1", "ap-2", "ap-2-1"}

    def test_stable_ids_are_the_upstream_hyphenated_codes_not_regenerated(self):
        index = parse_taxonomy_text(VALID_TEXT)
        bird = index.get("ap-2-1")
        assert bird is not None
        assert bird.code == "ap-2-1"
        assert bird.gid == "gid://shopify/TaxonomyCategory/ap-2-1"

    def test_reparsing_identical_text_produces_identical_stable_ids(self):
        first = parse_taxonomy_text(VALID_TEXT)
        second = parse_taxonomy_text(VALID_TEXT)
        assert set(first.by_code) == set(second.by_code)
        for code in first.by_code:
            assert first.get(code).to_dict() == second.get(code).to_dict()


class TestParentAndPathConsistency:
    def test_parent_code_is_the_code_with_its_last_segment_removed(self):
        index = parse_taxonomy_text(VALID_TEXT)
        assert index.get("ap").parent_code is None
        assert index.get("ap-2").parent_code == "ap"
        assert index.get("ap-2-1").parent_code == "ap-2"

    def test_level_equals_hyphen_segment_count(self):
        index = parse_taxonomy_text(VALID_TEXT)
        assert index.get("ap").level == 1
        assert index.get("ap-2").level == 2
        assert index.get("ap-2-1").level == 3

    def test_child_full_path_is_prefixed_by_parents_full_path(self):
        index = parse_taxonomy_text(VALID_TEXT)
        parent = index.get("ap-2")
        child = index.get("ap-2-1")
        assert child.full_path.startswith(parent.full_path + " > ")

    def test_rejects_a_category_whose_parent_is_missing_from_the_snapshot(self):
        text = "gid://shopify/TaxonomyCategory/ap-2-1 : Animals & Pet Supplies > Pet Supplies > Bird Supplies\n"
        with pytest.raises(CategoryTaxonomyError, match="parent"):
            parse_taxonomy_text(text)

    def test_rejects_a_path_depth_mismatched_with_its_code(self):
        # "ap-2" implies level 2, but the path only has one segment.
        text = "gid://shopify/TaxonomyCategory/ap : Animals & Pet Supplies\ngid://shopify/TaxonomyCategory/ap-2 : Pet Supplies\n"
        with pytest.raises(CategoryTaxonomyError, match="depth mismatch"):
            parse_taxonomy_text(text)

    def test_rejects_a_child_path_that_does_not_extend_its_parents_path(self):
        text = (
            "gid://shopify/TaxonomyCategory/ap : Animals & Pet Supplies\n"
            "gid://shopify/TaxonomyCategory/ap-2 : Something Else Entirely > Pet Supplies\n"
        )
        with pytest.raises(CategoryTaxonomyError, match="not a child path"):
            parse_taxonomy_text(text)


class TestDuplicateAndMalformedRecords:
    def test_rejects_a_duplicate_category_code(self):
        text = VALID_TEXT + "gid://shopify/TaxonomyCategory/ap : Animals & Pet Supplies\n"
        with pytest.raises(CategoryTaxonomyError, match="duplicate"):
            parse_taxonomy_text(text)

    def test_rejects_a_line_with_no_colon_separator(self):
        text = "gid://shopify/TaxonomyCategory/ap Animals & Pet Supplies\n"
        with pytest.raises(CategoryTaxonomyError, match="malformed taxonomy row"):
            parse_taxonomy_text(text)

    def test_rejects_a_line_with_no_gid_prefix(self):
        text = "not-a-gid-at-all : Animals & Pet Supplies\n"
        with pytest.raises(CategoryTaxonomyError, match="malformed taxonomy row"):
            parse_taxonomy_text(text)

    def test_rejects_an_empty_path_after_the_colon(self):
        text = "gid://shopify/TaxonomyCategory/ap :\n"
        with pytest.raises(CategoryTaxonomyError):
            parse_taxonomy_text(text)

    def test_rejects_a_code_with_a_double_hyphen(self):
        text = "gid://shopify/TaxonomyCategory/ap--1 : Animals & Pet Supplies > Live Animals\n"
        with pytest.raises(CategoryTaxonomyError, match="malformed taxonomy code"):
            parse_taxonomy_text(text)

    def test_rejects_a_taxonomy_with_zero_valid_rows(self):
        with pytest.raises(CategoryTaxonomyError, match="zero valid category rows"):
            parse_taxonomy_text("# only a comment\n\n")


class TestBundledSnapshot:
    def test_default_taxonomy_loads_and_validates_the_real_bundled_snapshot(self):
        index = default_taxonomy()
        assert len(index) > 1000
        # Every top-level vertical from the pinned snapshot must resolve.
        assert index.get("ap") is not None
        assert index.get("ap").level == 1
        assert index.get("ap").parent_code is None

    def test_default_taxonomy_is_cached_and_returns_the_same_content_on_repeat_calls(self):
        first = default_taxonomy()
        second = default_taxonomy()
        assert set(first.by_code) == set(second.by_code)

    def test_load_taxonomy_from_an_explicit_path_matches_default_taxonomy(self):
        from services.category_mapping.taxonomy_loader import _DEFAULT_SNAPSHOT_PATH
        explicit = load_taxonomy(_DEFAULT_SNAPSHOT_PATH)
        default = default_taxonomy()
        assert set(explicit.by_code) == set(default.by_code)
