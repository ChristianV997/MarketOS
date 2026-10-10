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


def _without_mapping(result: ProductAuditResult) -> dict:
    payload = result.to_dict()
    payload.pop("category_mapping_evidence", None)
    payload.pop("generated_at", None)  # wall-clock stamp, not audit content
    # The first audit is remembered as a "similar past product" by the second one. That is
    # existing run-history behaviour, independent of category mapping.
    validation = dict(payload.get("validation") or {})
    validation.pop("similar_past_products", None)
    payload["validation"] = validation
    return payload


def _summary_section(markdown: str) -> str:
    """The rendered Summary section (product, category, recommendation) only."""
    start = markdown.index("## Summary")
    end = markdown.index("\n## ", start + 1)
    return markdown[start:end]


class TestMappingCannotChangeDecisionOrReadiness:
    @pytest.mark.parametrize(
        "category",
        ["Bird Supplies", "Bags", "Completely Unrecognizable Made Up Thing"],  # mapped, ambiguous, unmapped
    )
    def test_audit_output_is_identical_with_and_without_mapping_evidence(self, monkeypatch, category):
        """Recommendation, status, pricing, blockers and every non-mapping field must not
        depend on whether (or how) the supplemental mapper ran."""
        from services.product_research.report import render_product_audit_markdown

        with_mapping, _ = run_product_audit("Widget", category=category)

        def _boom(*args, **kwargs):
            raise RuntimeError("simulated category mapping failure")

        monkeypatch.setattr("services.category_mapping.build_category_mapping_evidence", _boom)
        without_mapping, _ = run_product_audit("Widget", category=category)

        assert with_mapping.category_mapping_evidence is not None
        assert with_mapping.category_mapping_evidence["status"] in {"mapped", "ambiguous", "unmapped"}
        assert without_mapping.category_mapping_evidence is None
        assert _without_mapping(with_mapping) == _without_mapping(without_mapping)
        assert with_mapping.recommendation == without_mapping.recommendation
        assert with_mapping.status == without_mapping.status
        assert _summary_section(render_product_audit_markdown(with_mapping)) == _summary_section(
            render_product_audit_markdown(without_mapping)
        )
