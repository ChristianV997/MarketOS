"""Tests proving services.product_research.audit.run_product_audit composes
services.category_mapping as supplemental evidence, without becoming a
ranker/decision authority and without ever blocking the audit itself."""
from __future__ import annotations

import backend.core.persistence as pers
import pytest

from services.product_research.audit import run_product_audit
from services.product_research.schemas import ProductAuditResult


def _fake_signals(force_refresh=False):
    return [{"product": "Widget", "score": 0.8, "source": "mock", "platform": "mock"}]


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(pers, "STATE_DIR", str(tmp_path))
    from core.signals import signal_engine
    monkeypatch.setattr(signal_engine, "get", _fake_signals)


class TestCategoryMappingEvidenceComposition:
    def test_a_recognizable_category_produces_mapped_evidence(self):
        result, _ = run_product_audit("Widget", category="Bird Supplies")
        assert isinstance(result, ProductAuditResult)
        evidence = result.category_mapping_evidence
        assert evidence is not None
        assert evidence["status"] == "mapped"
        assert evidence["human_review_required"] is True
        assert evidence["decision_authority"] == "none"
        assert evidence["taxonomy_source"]["evidence_mode"] == "bundled_offline_snapshot"
        assert evidence["taxonomy_source"]["live_validation"] is False

    def test_an_unrecognizable_category_produces_unmapped_evidence_not_an_error(self):
        result, _ = run_product_audit("Widget", category="Completely Unrecognizable Made Up Thing")
        evidence = result.category_mapping_evidence
        assert evidence is not None
        assert evidence["status"] == "unmapped"
        assert evidence["candidates"] == []

    def test_category_mapping_evidence_never_overrides_the_callers_own_category_or_recommendation(self):
        result, _ = run_product_audit("Widget", category="Bird Supplies")
        assert result.category == "Bird Supplies"  # untouched by the mapper
        assert result.recommendation in ("green", "yellow", "red", "unknown")

    def test_a_category_mapping_failure_degrades_to_none_and_never_aborts_the_audit(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise RuntimeError("simulated category mapping failure")

        monkeypatch.setattr(
            "services.category_mapping.build_category_mapping_evidence", _boom
        )
        result, envelope = run_product_audit("Widget", category="Bird Supplies")
        assert result.category_mapping_evidence is None
        assert envelope.status == "completed"

        from services.product_research.report import render_product_audit_markdown
        markdown = render_product_audit_markdown(result)
        assert "category mapping evidence was not generated" in markdown
        assert "status**: unavailable" in markdown
        assert "status**: unmapped" not in markdown

    @pytest.mark.parametrize("failure", ["modified_artifact", "missing_artifact"])
    def test_a_bad_bundled_artifact_makes_evidence_unavailable_never_unmapped(self, failure, monkeypatch, tmp_path):
        # Exercises the real loader (not a patched builder): the failure must surface as
        # "unavailable" evidence, and the audit itself must still complete.
        from services.category_mapping import taxonomy_loader
        from services.product_research.report import render_product_audit_markdown

        raw = taxonomy_loader._DEFAULT_SNAPSHOT_PATH.read_bytes()
        target = tmp_path / "categories.v2026-08.partial.txt"
        if failure == "modified_artifact":
            target.write_bytes(raw.replace(b"\n", b"\r\n"))  # parses identically, bytes differ
        monkeypatch.setattr(taxonomy_loader, "_DEFAULT_SNAPSHOT_PATH", target)
        taxonomy_loader._cached_default_taxonomy.cache_clear()
        try:
            result, envelope = run_product_audit("Widget", category="Bird Supplies")
        finally:
            monkeypatch.undo()
            taxonomy_loader._cached_default_taxonomy.cache_clear()
        assert envelope.status == "completed"
        assert result.category_mapping_evidence is None
        assert result.to_dict()["category_mapping_evidence"] is None
        markdown = render_product_audit_markdown(result)
        assert "status**: unavailable" in markdown
        assert "status**: unmapped" not in markdown
        assert "bundled_offline_snapshot" not in markdown

    def test_markdown_exposes_taxonomy_evidence_as_offline_and_non_authoritative(self):
        from services.product_research.report import render_product_audit_markdown

        result, _ = run_product_audit("Widget", category="Coffee Grinders")
        markdown = render_product_audit_markdown(result)
        assert "Supplemental Category-Mapping Evidence" in markdown
        assert "not live validation" in markdown.lower()
        assert "bundled_offline_snapshot" in markdown
        assert "human_review_required" in markdown
        assert "decision_authority" in markdown

    def test_result_to_dict_includes_the_category_mapping_evidence_key(self):
        result, _ = run_product_audit("Widget", category="Bird Supplies")
        as_dict = result.to_dict()
        assert "category_mapping_evidence" in as_dict
