"""Tests for backend.mvp_commerce.supplier_evidence and its wiring into the
Commerce MVP economics/event pipeline (observed-over-assumed precedence)."""
from __future__ import annotations

from unittest.mock import patch

import backend.core.persistence as pers
import pytest

from backend.adapters.research.cj_public_evidence import CJProductEvidence
from backend.contracts.adapters import SidecarContext
from backend.mvp_commerce.runner import _economics, _economics_with_evidence
from backend.mvp_commerce.opportunity import build_opportunity_candidates_from_signals
from backend.mvp_commerce.supplier_evidence import (
    SupplierEvidenceResult, gather_supplier_evidence, supplier_evidence_events,
)
from backend.signals.public_sources import normalize_rss_xml


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(pers, "STATE_DIR", str(tmp_path))


_FIXTURE_XML = """<?xml version="1.0"?><rss><channel>
<item><title>Portable Espresso Maker Review</title><link>https://example.com/a</link>
<pubDate>Mon, 01 Jan 2026 00:00:00 GMT</pubDate><description>Great for travel</description></item>
<item><title>Best Portable Espresso Makers 2026</title><link>https://example.com/b</link>
<pubDate>Tue, 02 Jan 2026 00:00:00 GMT</pubDate><description>Compact and durable</description></item>
</channel></rss>"""


def _selected_candidate():
    signals, _ = normalize_rss_xml(_FIXTURE_XML, "portable espresso maker", source_url="https://x")
    candidates = build_opportunity_candidates_from_signals(signals, "ws", "portable espresso maker", 5)
    return candidates[0]


class TestEconomicsPrecedence:
    def test_default_economics_unchanged_without_evidence_param(self):
        """_economics() itself — the path every existing caller uses — is
        byte-for-byte untouched by this work."""
        candidate = _selected_candidate()
        result = _economics(candidate, 49.0, 15.0, 6.0, 12.0, 0.08, 0.03)
        assert result.source == "dry_run_assumption"
        assert result.assumptions == (
            "Assumed price=49.0", "Assumed unit cost=15.0", "Assumed shipping=6.0",
            "Assumed CAC=12.0", "Assumed return rate=0.08",
        )

    def test_observed_evidence_overrides_assumed_cost_and_shipping(self):
        candidate = _selected_candidate()

        class _Evidence:
            unit_cost = 9.5
            shipping_cost = 2.25
            source_url = "https://www.cjdropshipping.com/product/example.html"

        result = _economics_with_evidence(candidate, 49.0, 15.0, 6.0, 12.0, 0.08, 0.03, evidence=_Evidence())
        assert result.source == "partial_observed_supplier_evidence"
        assert result.assumed_unit_cost == 9.5
        assert result.assumed_shipping_cost == 2.25
        assert "Observed CJ supplier cost=9.5" in result.assumptions[1]
        assert "Observed CJ shipping=2.25" in result.assumptions[2]
        # price/CAC/return-rate remain plain assumptions — only supplier
        # cost/shipping are ever marked observed.
        assert result.assumptions[0] == "Assumed price=49.0"
        assert result.assumptions[3] == "Assumed CAC=12.0"

    def test_partial_evidence_only_overrides_the_observed_component(self):
        candidate = _selected_candidate()

        class _CostOnlyEvidence:
            unit_cost = 9.5
            shipping_cost = None
            source_url = "https://www.cjdropshipping.com/product/example.html"

        result = _economics_with_evidence(candidate, 49.0, 15.0, 6.0, 12.0, 0.08, 0.03, evidence=_CostOnlyEvidence())
        assert result.assumed_unit_cost == 9.5
        assert result.assumed_shipping_cost == 6.0  # unchanged assumption
        assert "Observed CJ supplier cost" in result.assumptions[1]
        assert result.assumptions[2] == "Assumed shipping=6.0"

    def test_no_evidence_at_all_falls_back_to_assumptions_with_evidence_path(self):
        candidate = _selected_candidate()
        result = _economics_with_evidence(candidate, 49.0, 15.0, 6.0, 12.0, 0.08, 0.03, evidence=None)
        assert result.source == "dry_run_assumption"
        assert result.assumed_unit_cost == 15.0


class TestGatherSupplierEvidence:
    def test_no_candidate_urls_and_no_discovery_returns_not_attempted(self):
        with patch("backend.mvp_commerce.supplier_evidence.discover_candidate_urls", return_value=[]):
            result = gather_supplier_evidence("portable espresso maker", context=SidecarContext(dry_run=False))
        assert result.attempted is True
        assert result.unit_cost is None
        assert "no_candidate_urls" in result.warnings[0]

    def test_dry_run_never_calls_network_and_returns_no_cost(self):
        result = gather_supplier_evidence(
            "portable espresso maker", context=SidecarContext(dry_run=True),
            candidate_urls=["https://www.cjdropshipping.com/product/x.html"],
        )
        # Dry-run evidence is always degraded (no observed price), so no
        # priced candidate exists — economics stays on assumptions.
        assert result.unit_cost is None
        assert result.evidence is None
        assert result.candidates_considered == 1
        assert result.ranking[0]["extraction_confidence"] == 0.0

    def test_best_priced_candidate_is_selected(self):
        good = CJProductEvidence(
            source="cj_public_page", source_url="https://www.cjdropshipping.com/product/good.html",
            observed_at=0.0, external_product_id="good", title="Portable Espresso Maker",
            field_status={"title": "observed", "price": "observed"}, price=9.5, shipping_cost=2.0,
            confidence=0.9,
        )
        bad = CJProductEvidence(
            source="cj_public_page", source_url="https://www.cjdropshipping.com/product/bad.html",
            observed_at=0.0, external_product_id="bad", title="Unrelated Gadget",
            field_status={"title": "observed"}, price=None, confidence=0.1,
        )
        with patch("backend.mvp_commerce.supplier_evidence.fetch_product_evidence", side_effect=[bad, good]):
            result = gather_supplier_evidence(
                "portable espresso maker", context=SidecarContext(dry_run=False),
                candidate_urls=["https://www.cjdropshipping.com/product/bad.html", "https://www.cjdropshipping.com/product/good.html"],
            )
        assert result.unit_cost == 9.5
        assert result.shipping_cost == 2.0
        assert result.source_url == "https://www.cjdropshipping.com/product/good.html"
        assert result.candidates_considered == 2

    def test_no_priced_candidates_returns_none_cost_with_ranking(self):
        unpriced = CJProductEvidence(
            source="cj_public_page", source_url="https://www.cjdropshipping.com/product/x.html",
            observed_at=0.0, external_product_id="x", title="Something",
            field_status={"title": "observed"}, price=None, confidence=0.3,
        )
        with patch("backend.mvp_commerce.supplier_evidence.fetch_product_evidence", return_value=unpriced):
            result = gather_supplier_evidence(
                "something", context=SidecarContext(dry_run=False),
                candidate_urls=["https://www.cjdropshipping.com/product/x.html"],
            )
        assert result.unit_cost is None
        assert result.ranking


class TestSupplierEvidenceEvents:
    def test_events_for_observed_evidence(self):
        evidence = CJProductEvidence(
            source="cj_public_page", source_url="https://www.cjdropshipping.com/product/good.html",
            observed_at=0.0, external_product_id="good", title="Portable Espresso Maker",
            field_status={"title": "observed", "price": "observed"}, price=9.5, confidence=0.9,
        )
        result = SupplierEvidenceResult(
            attempted=True, unit_cost=9.5, shipping_cost=None, source_url=evidence.source_url,
            candidates_considered=1, evidence=evidence,
        )
        events = supplier_evidence_events(result, workspace_id="ws", run_id="run-1", occurred_at=1_700_000_000.0)
        types = [event.event_type for event in events]
        assert types == ["supplier_evidence_requested", "supplier_product_observed", "commerce_economics_enriched"]
        assert all(event.correlation_id == "run-1" for event in events)
        assert all(event.metadata["no_order_authority"] is True for event in events)
        assert events[1].payload["external_product_id"] == "good"

    def test_events_for_degraded_evidence(self):
        result = SupplierEvidenceResult(
            attempted=True, unit_cost=None, shipping_cost=None, source_url="",
            warnings=("no_candidate_urls: supply candidate_urls or rely on discovery",),
        )
        events = supplier_evidence_events(result, workspace_id="ws", run_id="run-2", occurred_at=1_700_000_000.0)
        types = [event.event_type for event in events]
        assert types == ["supplier_evidence_requested", "supplier_evidence_degraded"]

    def test_event_ids_deterministic(self):
        evidence = CJProductEvidence(
            source="cj_public_page", source_url="https://www.cjdropshipping.com/product/x.html",
            observed_at=0.0, external_product_id="x", title="Widget",
            field_status={"title": "observed", "price": "observed"}, price=5.0, confidence=0.5,
        )
        result = SupplierEvidenceResult(attempted=True, unit_cost=5.0, shipping_cost=None, source_url=evidence.source_url, evidence=evidence)
        first = supplier_evidence_events(result, workspace_id="ws", run_id="run-3", occurred_at=1.0)
        second = supplier_evidence_events(result, workspace_id="ws", run_id="run-3", occurred_at=1.0)
        assert [e.event_id for e in first] == [e.event_id for e in second]
