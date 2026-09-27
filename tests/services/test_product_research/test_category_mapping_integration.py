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

    def test_result_to_dict_includes_the_category_mapping_evidence_key(self):
        result, _ = run_product_audit("Widget", category="Bird Supplies")
        as_dict = result.to_dict()
        assert "category_mapping_evidence" in as_dict
