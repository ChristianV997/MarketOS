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

    def test_bundled_snapshot_provenance_is_offline_and_includes_its_curated_artifact_digest(self):
        source = default_taxonomy().source_provenance
        assert source["evidence_mode"] == "bundled_offline_snapshot"
        assert source["live_validation"] is False
        assert source["snapshot_sha256"] == "e2c0193602e5a21afadf5ffc940cec4975eeec2e698fe33d9cb1437d106dedb2"

    def test_custom_snapshot_path_is_not_attributed_to_the_pinned_shopify_release(self, tmp_path):
        path = tmp_path / "fixture-taxonomy.txt"
        path.write_text(VALID_TEXT, encoding="utf-8")
        source = load_taxonomy(path).source_provenance
        assert source["evidence_mode"] == "unverified_local_file"
        assert source["live_validation"] is False
        assert "repository_url" not in source
        assert "commit_sha" not in source

    def test_bundled_snapshot_digest_mismatch_fails_closed(self, tmp_path, monkeypatch):
        from services.category_mapping import taxonomy_loader

        tampered_snapshot = tmp_path / "categories.v2026-08.partial.txt"
        tampered_snapshot.write_text(VALID_TEXT, encoding="utf-8")
        monkeypatch.setattr(taxonomy_loader, "_DEFAULT_SNAPSHOT_PATH", tampered_snapshot)
        with pytest.raises(CategoryTaxonomyError, match="snapshot checksum mismatch"):
            taxonomy_loader.load_taxonomy()

    @pytest.mark.parametrize(
        "mutate",
        [
            pytest.param(lambda raw: raw.replace(b"\n", b"\r\n"), id="crlf_line_endings"),
            pytest.param(lambda raw: raw.replace(b"\n", b"\r"), id="lone_cr_line_endings"),
            pytest.param(lambda raw: raw + b"\n", id="extra_trailing_newline"),
            pytest.param(lambda raw: raw.replace(b"\n", b"  \n", 1), id="trailing_whitespace"),
            pytest.param(lambda raw: raw.replace(b"Apparel", b"Apparal", 1), id="one_byte_edit"),
            pytest.param(lambda raw: raw[: len(raw) // 2], id="truncated"),
            pytest.param(lambda raw: b"", id="empty"),
            pytest.param(lambda raw: raw + b"\xff", id="invalid_utf8_appended"),
        ],
    )
    def test_any_byte_level_modification_of_the_bundled_artifact_fails_closed(self, tmp_path, monkeypatch, mutate):
        # The digest covers raw bytes: a copy that parses identically (CRLF/CR rewrites) is
        # still a modified artifact and must not be attributed to the bundled snapshot.
        from services.category_mapping import taxonomy_loader

        raw = taxonomy_loader._DEFAULT_SNAPSHOT_PATH.read_bytes()
        modified = tmp_path / "categories.v2026-08.partial.txt"
        modified.write_bytes(mutate(raw))
        monkeypatch.setattr(taxonomy_loader, "_DEFAULT_SNAPSHOT_PATH", modified)
        with pytest.raises(CategoryTaxonomyError, match="snapshot checksum mismatch"):
            taxonomy_loader.load_taxonomy()

    def test_missing_bundled_artifact_raises_the_module_error_not_an_os_error(self, tmp_path, monkeypatch):
        from services.category_mapping import taxonomy_loader

        monkeypatch.setattr(taxonomy_loader, "_DEFAULT_SNAPSHOT_PATH", tmp_path / "absent.txt")
        with pytest.raises(CategoryTaxonomyError, match="snapshot unreadable"):
            taxonomy_loader.load_taxonomy()

    def test_missing_or_non_utf8_alternate_snapshot_raises_the_module_error(self, tmp_path):
        with pytest.raises(CategoryTaxonomyError, match="snapshot unreadable"):
            load_taxonomy(tmp_path / "absent.txt")
        bad = tmp_path / "bad.txt"
        bad.write_bytes(b"gid://shopify/TaxonomyCategory/ap : Animals \xff")
        with pytest.raises(CategoryTaxonomyError, match="not valid UTF-8"):
            load_taxonomy(bad)

    def test_a_path_containing_a_nul_byte_raises_the_module_error(self):
        from pathlib import Path

        with pytest.raises(CategoryTaxonomyError, match="snapshot unreadable"):
            load_taxonomy(Path("a\0b"))

    def test_a_directory_is_not_a_regular_file(self, tmp_path):
        with pytest.raises(CategoryTaxonomyError, match="not a regular file"):
            load_taxonomy(tmp_path)

    @pytest.mark.skipif(not hasattr(__import__("os"), "mkfifo"), reason="needs POSIX FIFOs")
    def test_a_fifo_is_rejected_without_blocking(self, tmp_path):
        import os
        import subprocess
        import sys
        from pathlib import Path

        fifo = tmp_path / "snapshot.fifo"
        os.mkfifo(fifo)
        code = (
            "import sys; from pathlib import Path; "
            "from services.category_mapping.taxonomy_loader import load_taxonomy; "
            "from services.category_mapping.schemas import CategoryTaxonomyError\n"
            "try:\n    load_taxonomy(Path(sys.argv[1]))\nexcept CategoryTaxonomyError as e:\n    print('typed', e)\n"
        )
        repo_root = Path(__file__).resolve().parents[3]
        result = subprocess.run(
            [sys.executable, "-c", code, str(fifo)], cwd=repo_root, capture_output=True, text=True, timeout=30
        )
        assert result.stdout.startswith("typed taxonomy snapshot is not a regular file"), result

    def test_an_oversized_snapshot_is_rejected_before_it_is_read_whole(self, tmp_path, monkeypatch):
        from services.category_mapping import taxonomy_loader

        monkeypatch.setattr(taxonomy_loader, "_MAX_SNAPSHOT_BYTES", 1024)
        big = tmp_path / "big.txt"
        big.write_bytes(b"#" * 2048)
        with pytest.raises(CategoryTaxonomyError, match="exceeds 1024 bytes"):
            load_taxonomy(big)
        # the real bundled file is far below the bound and still loads
        monkeypatch.undo()
        assert len(default_taxonomy()) > 0

    def test_byte_identical_copy_elsewhere_is_unverified_not_bundled_evidence(self, tmp_path):
        from services.category_mapping import taxonomy_loader

        copy = tmp_path / "copy.txt"
        copy.write_bytes(taxonomy_loader._DEFAULT_SNAPSHOT_PATH.read_bytes())
        source = load_taxonomy(copy).source_provenance
        assert source["evidence_mode"] == "unverified_local_file"
        assert source["live_validation"] is False
        assert "snapshot_sha256" not in source and "commit_sha" not in source

    def test_curated_sub_level_three_categories_resolve_with_valid_parents(self):
        index = default_taxonomy()
        # Level 4 curated categories
        feeder = index.get("ap-2-14-1")
        assert feeder is not None
        assert feeder.level == 4
        assert feeder.name == "Automatic Feeders"
        assert feeder.parent_code == "ap-2-14"
        assert feeder.full_path == (
            "Animals & Pet Supplies > Pet Supplies > Pet Bowls, Feeders & Waterers > Automatic Feeders"
        )

        flat_bands = index.get("sg-2-6-4")
        assert flat_bands is not None
        assert flat_bands.level == 4
        assert flat_bands.name == "Flat Resistance Bands"
        assert flat_bands.parent_code == "sg-2-6"

        lunch_boxes = index.get("hg-11-3-7")
        assert lunch_boxes is not None
        assert lunch_boxes.level == 4
        assert lunch_boxes.name == "Lunch Boxes & Totes"
        assert lunch_boxes.parent_code == "hg-11-3"

        # Level 5 curated categories
        espresso = index.get("hg-11-7-4-3")
        assert espresso is not None
        assert espresso.level == 5
        assert espresso.name == "Espresso Machines"
        assert espresso.parent_code == "hg-11-7-4"
        assert espresso.full_path == (
            "Home & Garden > Kitchen & Dining > Kitchen Appliances > "
            "Coffee Makers & Espresso Machines > Espresso Machines"
        )

        grinders = index.get("hg-11-6-2-6")
        assert grinders is not None
        assert grinders.level == 5
        assert grinders.name == "Coffee Grinders"
        assert grinders.parent_code == "hg-11-6-2"

        bento = index.get("hg-11-3-7-5")
        assert bento is not None
        assert bento.level == 5
        assert bento.name == "Bento Boxes"
        assert bento.parent_code == "hg-11-3-7"


class TestTaxonomyIndexImmutability:
    def test_taxonomy_index_by_code_is_genuinely_immutable(self):
        index = parse_taxonomy_text(VALID_TEXT)

        with pytest.raises(TypeError):
            index.by_code["new_code"] = None  # type: ignore[index]

        with pytest.raises(AttributeError):
            index.by_code.clear()  # type: ignore[attr-defined]

        with pytest.raises(AttributeError):
            index.by_code.pop("ap")  # type: ignore[attr-defined]

    def test_default_taxonomy_cache_cannot_be_poisoned(self):
        t1 = default_taxonomy()
        orig_len = len(t1)

        with pytest.raises(TypeError):
            t1.by_code["malicious_code"] = None  # type: ignore[index]

        with pytest.raises(AttributeError):
            t1.by_code.clear()  # type: ignore[attr-defined]

        t2 = default_taxonomy()
        assert len(t2) == orig_len
        assert "malicious_code" not in t2.by_code

    def test_taxonomy_index_defensive_copy_on_construction(self):
        from services.category_mapping.taxonomy_loader import TaxonomyIndex
        index = parse_taxonomy_text(VALID_TEXT)
        mutable_dict = dict(index.by_code)
        custom_index = TaxonomyIndex(by_code=mutable_dict)

        mutable_dict["extra_key"] = None  # type: ignore[assignment]
        assert "extra_key" not in custom_index.by_code
        with pytest.raises(TypeError):
            custom_index.by_code["extra_key"] = None  # type: ignore[index]


class TestPartialSnapshotRepresentation:
    def test_bundled_snapshot_is_declared_partial_and_pinned(self):
        from services.category_mapping.schemas import TAXONOMY_SOURCE_PROVENANCE
        from services.category_mapping.taxonomy_loader import _DEFAULT_SNAPSHOT_PATH

        header = "\n".join(
            line for line in _DEFAULT_SNAPSHOT_PATH.read_text(encoding="utf-8").splitlines() if line.startswith("#")
        )
        assert "PARTIAL SNAPSHOT" in header
        assert "NOT a full taxonomy mirror" in header
        assert TAXONOMY_SOURCE_PROVENANCE["commit_sha"] in header
        assert TAXONOMY_SOURCE_PROVENANCE["version_tag"] in header

    def test_bundled_snapshot_has_no_rows_deeper_than_level_five(self):
        assert max(category.level for category in default_taxonomy()) <= 5

    def test_snapshot_rows_are_sorted_deterministically_on_reload(self):
        first = [c.code for c in load_taxonomy()]
        second = [c.code for c in load_taxonomy()]
        assert first == second
