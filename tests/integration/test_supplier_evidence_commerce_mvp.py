"""Tests for backend.mvp_commerce.supplier_evidence and its wiring into the
Commerce MVP economics/event pipeline (observed-over-assumed precedence)."""
from __future__ import annotations

import json
import socket
from unittest.mock import patch

import backend.core.persistence as pers
import pytest

from backend.adapters.research import cj_public_evidence as cj_mod
from backend.adapters.research.cj_public_evidence import CJProductEvidence
from backend.contracts.adapters import SidecarContext
from backend.mvp_commerce.public_run import run_commerce_mvp_from_public_rss
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

_MISSING = object()
_FETCHED_AT = 1_700_000_000.0
_CJ_URL_PREFIX = "https://www.cjdropshipping.com/product"


@pytest.fixture(autouse=True)
def _block_supplier_network(monkeypatch):
    """All end-to-end supplier evidence uses fixture DNS and mocked transport."""
    def _blocked(*_args, **_kwargs):
        raise AssertionError("network transport is disabled in supplier-evidence tests")

    def _fixture_dns(*_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("1.1.1.1", 443))]

    monkeypatch.setattr(socket, "getaddrinfo", _fixture_dns)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
    monkeypatch.setattr(cj_mod, "_check_robots", lambda *_args, **_kwargs: None)
    cj_mod._CACHE.clear()
    yield
    cj_mod._CACHE.clear()


def _jsonld_page(*, price, currency, shipping, shipping_currency):
    offer = {}
    if price is not _MISSING:
        offer["price"] = price
    if currency is not None:
        offer["priceCurrency"] = currency
    if shipping is not _MISSING:
        rate = {"value": shipping}
        if shipping_currency is not None:
            rate["currency"] = shipping_currency
        offer["shippingDetails"] = {"shippingRate": rate}
    product = {
        "@context": "https://schema.org", "@type": "Product",
        "name": "Portable Espresso Maker", "sku": "CJ-ESP-001", "offers": offer,
    }
    return '<script type="application/ld+json">' + json.dumps(product) + "</script>"


def _run_public_page(monkeypatch, *, page_key, page_html, fetch_page=None, now=_FETCHED_AT):
    url = f"{_CJ_URL_PREFIX}/{page_key}.html"
    monkeypatch.setattr(cj_mod.time, "time", lambda: now)
    monkeypatch.setattr(cj_mod, "_bounded_get", fetch_page or (lambda _url: page_html))
    return run_commerce_mvp_from_public_rss(
        workspace_id=f"ws-{page_key}",
        query="portable espresso maker",
        allow_network=True,
        fetcher=lambda _url, _limit: _FIXTURE_XML,
        attempt_supplier_evidence=True,
        supplier_candidate_urls=[url],
        use_opportunity_ranking=True,
    )


def _event(result, event_type):
    return next(event for event in result.events if event.event_type == event_type)


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
            currency = "USD"
            shipping_currency = "USD"
            source_url = "https://www.cjdropshipping.com/product/example.html"
            source_type = "public_page_static"

        result = _economics_with_evidence(candidate, 49.0, 15.0, 6.0, 12.0, 0.08, 0.03, evidence=_Evidence())
        assert result.source == "partial_observed_public_page_evidence"
        assert result.assumed_unit_cost == 9.5
        assert result.assumed_shipping_cost == 2.25
        assert "Observed CJ public-page catalog price (not supplier-live proof)=9.5" in result.assumptions[1]
        assert "Observed CJ public-page shipping value (not supplier-live proof)=2.25" in result.assumptions[2]
        # price/CAC/return-rate remain plain assumptions — only supplier
        # cost/shipping are ever marked observed.
        assert result.assumptions[0] == "Assumed price=49.0"
        assert result.assumptions[3] == "Assumed CAC=12.0"

    def test_partial_evidence_only_overrides_the_observed_component(self):
        candidate = _selected_candidate()

        class _CostOnlyEvidence:
            unit_cost = 9.5
            shipping_cost = None
            currency = "USD"
            shipping_currency = None
            source_url = "https://www.cjdropshipping.com/product/example.html"
            source_type = "public_page_static"

        result = _economics_with_evidence(candidate, 49.0, 15.0, 6.0, 12.0, 0.08, 0.03, evidence=_CostOnlyEvidence())
        assert result.assumed_unit_cost == 9.5
        assert result.assumed_shipping_cost == 6.0  # unchanged assumption
        assert "public-page catalog price (not supplier-live proof)" in result.assumptions[1]
        assert result.assumptions[2].startswith("Assumed shipping=6.0; public-page shipping unavailable")

    def test_zero_public_page_price_does_not_replace_assumed_supplier_cost(self):
        candidate = _selected_candidate()

        class _ZeroCostEvidence:
            unit_cost = 0.0
            shipping_cost = 0.0
            currency = "USD"
            shipping_currency = "USD"
            source_url = "https://www.cjdropshipping.com/product/example.html"
            source_type = "public_page_static"

        result = _economics_with_evidence(candidate, 49.0, 15.0, 6.0, 12.0, 0.08, 0.03, evidence=_ZeroCostEvidence())
        assert result.assumed_unit_cost == 15.0
        assert result.assumed_shipping_cost == 0.0
        assert "Assumed unit cost=15.0" in result.assumptions[1]
        assert "public-page shipping value" in result.assumptions[2]

    def test_currency_mismatch_keeps_usd_assumptions_and_explains_rejection(self):
        candidate = _selected_candidate()

        class _Evidence:
            unit_cost = 9.5
            shipping_cost = 2.25
            currency = "EUR"
            shipping_currency = "USD"
            fetched_at = _FETCHED_AT
            fetch_provenance = "cache_hit"
            source_url = "https://www.cjdropshipping.com/product/example.html"
            source_type = "public_page_static"
            evidence = None
            warnings = ("unit_cost_currency_mismatch: observed EUR; economics require USD",)

        result = _economics_with_evidence(candidate, 49.0, 15.0, 6.0, 12.0, 0.08, 0.03, evidence=_Evidence())

        assert result.assumed_unit_cost == 15.0
        assert result.assumed_shipping_cost == 2.25
        assert any("currency_mismatch" in warning.lower() for warning in result.warnings)
        assert "EUR" in " ".join(result.assumptions)
        assert str(_FETCHED_AT) in " ".join(result.assumptions)

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
            field_status={"title": "observed", "price": "observed", "shipping_cost": "observed"},
            price=9.5, currency="USD", shipping_cost=2.0, shipping_currency="USD",
            confidence=0.9, fetch_provenance="fresh_fetch",
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
        assert result.source_type == "public_page_static"
        assert result.evidence is not None
        assert result.evidence.source == "cj_public_page"

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

    def test_missing_shipping_is_assumed_and_zero_shipping_is_observed(self):
        url = "https://www.cjdropshipping.com/product/shipping.html"

        def _evidence(shipping_cost):
            return CJProductEvidence(
                source="cj_public_page", source_url=url, observed_at=1_700_000_000.0,
                external_product_id="shipping-widget", title="Portable Espresso Maker",
                field_status={"title": "observed", "price": "observed",
                              "shipping_cost": "unavailable" if shipping_cost is None else "observed"},
                price=9.5, currency="USD", shipping_cost=shipping_cost,
                shipping_currency="USD" if shipping_cost is not None else None, confidence=0.9,
                fetch_provenance="fresh_fetch",
            )

        missing_shipping = _evidence(None)
        with patch("backend.mvp_commerce.supplier_evidence.fetch_product_evidence", return_value=missing_shipping):
            missing = gather_supplier_evidence(
                "portable espresso maker", context=SidecarContext(dry_run=False), candidate_urls=[url],
            )
        assert missing.shipping_cost is None
        assert "shipping_cost: unavailable_publicly" in missing.warnings

        zero_shipping = _evidence(0.0)
        with patch("backend.mvp_commerce.supplier_evidence.fetch_product_evidence", return_value=zero_shipping):
            zero = gather_supplier_evidence(
                "portable espresso maker", context=SidecarContext(dry_run=False), candidate_urls=[url],
            )
        assert zero.shipping_cost == 0.0
        assert "shipping_cost: unavailable_publicly" not in zero.warnings


class TestSupplierEvidenceEvents:
    def test_events_for_observed_evidence(self):
        evidence = CJProductEvidence(
            source="cj_public_page", source_url="https://www.cjdropshipping.com/product/good.html",
            observed_at=0.0, external_product_id="good", title="Portable Espresso Maker",
            field_status={"title": "observed", "price": "observed"}, price=9.5, confidence=0.9,
            fetch_provenance="cache_hit",
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
        assert events[1].payload["fetch_provenance"] == "cache_hit"
        assert events[1].metadata["no_outreach_authority"] is True
        assert events[1].metadata["public_source"] is True
        assert events[1].metadata["authenticated_readonly"] is False
        assert events[1].metadata["supplier_source"] == "public_page_static"
        assert events[2].payload["fetch_provenance"] == "cache_hit"
        assert events[2].payload["observed_at"] == 0.0


class TestPublicRunEvidenceContract:
    def test_actual_public_run_preserves_zero_vs_missing_and_shipping_semantics(self, monkeypatch):
        zero = _run_public_page(
            monkeypatch, page_key="zero",
            page_html=_jsonld_page(price=0, currency="USD", shipping=0, shipping_currency="USD"),
        )
        missing = _run_public_page(
            monkeypatch, page_key="missing",
            page_html=_jsonld_page(price=_MISSING, currency=None, shipping=_MISSING, shipping_currency=None),
        )

        zero_observed = _event(zero, "supplier_product_observed")
        missing_observed = _event(missing, "supplier_product_observed")
        zero_summary = zero.run.unit_economics_summary
        missing_summary = missing.run.unit_economics_summary
        assert zero_summary is not None and missing_summary is not None
        assert zero_observed.payload["price"] == 0.0
        assert zero_observed.payload["field_status"]["price"] == "observed"
        assert missing_observed.payload["price"] is None
        assert missing_observed.payload["field_status"]["price"] == "unavailable"
        assert zero_summary.assumed_unit_cost == 15.0
        assert zero_summary.assumed_shipping_cost == 0.0
        assert missing_summary.assumed_unit_cost == 15.0
        assert missing_summary.assumed_shipping_cost == 6.0
        assert "price_not_usable_as_supplier_cost" in zero_summary.warnings
        assert "shipping_cost: unavailable_publicly" not in zero_summary.warnings
        assert "shipping_cost: unavailable_publicly" in missing_summary.warnings

    def test_actual_public_run_rejects_currency_mismatch_and_emits_provenance_and_authority(self, monkeypatch):
        result = _run_public_page(
            monkeypatch, page_key="eur",
            page_html=_jsonld_page(price="9.50", currency="EUR", shipping="2.25", shipping_currency="USD"),
        )
        observed = _event(result, "supplier_product_observed")
        economics = _event(result, "commerce_economics_enriched")
        report = result.to_dict()
        summary = result.run.unit_economics_summary
        assert summary is not None

        assert observed.payload["currency"] == "EUR"
        assert observed.payload["shipping_currency"] == "USD"
        assert observed.payload["fetched_at"] == _FETCHED_AT
        assert observed.payload["observed_at"] == _FETCHED_AT
        assert observed.payload["fetch_provenance"] == "fresh_fetch"
        assert observed.metadata["supplier_source"] == "public_page_static"
        assert observed.metadata["authenticated_readonly"] is False
        assert economics.payload["unit_cost"] is None
        assert economics.payload["currency"] == "EUR"
        assert economics.payload["shipping_currency"] == "USD"
        assert summary.assumed_unit_cost == 15.0
        assert summary.assumed_shipping_cost == 2.25
        assert any("currency_mismatch" in warning.lower() for warning in summary.warnings)
        assert "EUR" in " ".join(summary.assumptions)
        assert str(_FETCHED_AT) in " ".join(summary.assumptions)
        scored = _event(result, "candidate_scored")
        score_dimensions = {item["name"]: item for item in scored.payload["dimensions"]}
        assert score_dimensions["observed_supplier_cost"]["is_unknown"] is True
        assert score_dimensions["observed_supplier_cost"]["raw_value"] is None
        assert "EUR" in score_dimensions["supplier_evidence_quality"]["reason"]
        assert f"fetched_at={_FETCHED_AT}" in score_dimensions["supplier_evidence_quality"]["reason"]
        assert "not supplier-live proof" in score_dimensions["supplier_evidence_quality"]["reason"]
        assert score_dimensions["shipping_complexity"]["provenance"] == "public_page"
        assert report["read_only"] is True and report["advisory"] is True and report["mutated"] is False
        authority_flags = ("no_launch_authority", "no_ad_authority", "no_order_authority", "no_payment_authority")
        assert all(report["run"]["metadata"].get(flag) is True for flag in authority_flags)
        assert result.events
        assert all(event.metadata.get("non_authoritative") is True for event in result.events)
        guarded_events = [event for event in result.events if event.event_type in {
            "supplier_evidence_requested", "supplier_product_observed", "commerce_economics_enriched",
            "candidate_scored", "opportunity_scoring_completed",
        }]
        assert guarded_events
        assert all(all(event.metadata.get(flag) is True for flag in authority_flags) for event in guarded_events)

    def test_actual_public_run_does_not_assume_currency_when_page_omits_it(self, monkeypatch):
        result = _run_public_page(
            monkeypatch, page_key="currency-unknown",
            page_html=_jsonld_page(price="9.50", currency=None, shipping=_MISSING, shipping_currency=None),
        )
        observed = _event(result, "supplier_product_observed")
        summary = result.run.unit_economics_summary
        assert summary is not None

        assert observed.payload["price"] == 9.5
        assert observed.payload["currency"] is None
        assert observed.payload["field_status"]["currency"] == "unavailable"
        assert summary.assumed_unit_cost == 15.0
        assert any("currency_unavailable" in warning for warning in summary.warnings)
        assert "currency unknown" in summary.assumptions[1]

    def test_actual_public_run_rejects_shipping_currency_mismatch(self, monkeypatch):
        result = _run_public_page(
            monkeypatch, page_key="shipping-eur",
            page_html=_jsonld_page(price="9.50", currency="USD", shipping="2.25", shipping_currency="EUR"),
        )
        observed = _event(result, "supplier_product_observed")
        economics = _event(result, "commerce_economics_enriched")
        summary = result.run.unit_economics_summary
        assert summary is not None

        assert observed.payload["currency"] == "USD"
        assert observed.payload["shipping_cost"] == 2.25
        assert observed.payload["shipping_currency"] == "EUR"
        assert economics.payload["unit_cost"] == 9.5
        assert economics.payload["shipping_cost"] is None
        assert summary.assumed_unit_cost == 9.5
        assert summary.assumed_shipping_cost == 6.0
        assert any("shipping_currency_mismatch" in warning for warning in summary.warnings)
        assert "rejected public-page shipping=2.25 EUR" in summary.assumptions[2]
        scored = _event(result, "candidate_scored")
        score_dimensions = {item["name"]: item for item in scored.payload["dimensions"]}
        assert score_dimensions["shipping_complexity"]["is_unknown"] is True
        assert "currency=USD" in score_dimensions["supplier_evidence_quality"]["reason"]

    def test_actual_public_run_cache_hit_reuses_fetch_time(self, monkeypatch):
        html = _jsonld_page(price="9.50", currency="USD", shipping="2.25", shipping_currency="USD")
        calls = []

        def _fixture_fetch(url):
            calls.append(url)
            return html

        first = _run_public_page(monkeypatch, page_key="cached", page_html=html, fetch_page=_fixture_fetch)
        second = _run_public_page(
            monkeypatch, page_key="cached", page_html=html, fetch_page=_fixture_fetch,
            now=_FETCHED_AT + 3600,
        )
        first_observed = _event(first, "supplier_product_observed").payload
        second_observed = _event(second, "supplier_product_observed").payload

        assert calls == [f"{_CJ_URL_PREFIX}/cached.html"]
        assert first_observed["fetched_at"] == second_observed["fetched_at"] == _FETCHED_AT
        assert second_observed["fetched_at"] != _FETCHED_AT + 3600
        assert first_observed["fetch_provenance"] == "fresh_fetch"
        assert second_observed["fetch_provenance"] == "cache_hit"
        assert _event(second, "commerce_economics_enriched").payload["fetched_at"] == _FETCHED_AT

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
