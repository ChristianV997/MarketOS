"""Tests for backend.mvp_commerce.competition_intelligence."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.adapters.research import competition_evidence as ce_mod
from backend.contracts.adapters import SidecarContext
from backend.contracts.events import Event
from backend.mvp_commerce import competition_intelligence as mod
from backend.mvp_commerce.supplier_evidence import SupplierEvidenceResult

HTML_A = """<html><head><script type="application/ld+json">
{"@type": "Product", "name": "Portable Espresso Maker", "brand": {"name": "Acme"},
 "aggregateRating": {"ratingValue": "4.2", "reviewCount": "80"},
 "offers": {"price": "32.00", "priceCurrency": "USD", "availability": "InStock", "seller": {"name": "Store A"}}}
</script></head></html>"""

HTML_B = """<html><head><script type="application/ld+json">
{"@type": "Product", "name": "Portable Espresso Maker Pro", "brand": {"name": "Zenith"},
 "aggregateRating": {"ratingValue": "3.9", "reviewCount": "40"},
 "offers": {"price": "27.50", "priceCurrency": "USD", "availability": "InStock", "seller": {"name": "Store B"}}}
</script></head></html>"""

NO_PRODUCT_HTML = "<html><body><p>no structured data</p></body></html>"


@pytest.fixture(autouse=True)
def _clear_cache():
    ce_mod._CACHE.clear()
    yield
    ce_mod._CACHE.clear()


@pytest.fixture(autouse=True)
def _no_real_robots_fetch():
    with patch.object(ce_mod, "_check_robots", return_value=None):
        yield


@pytest.fixture(autouse=True)
def _no_real_dns_resolution():
    """These fixture domains (a.example.com/b.example.com) aren't real
    resolvable hosts; skip DNS resolution the same way robots.txt is
    skipped above -- URL-safety itself is exercised directly against
    real/known-bad hosts in test_competition_evidence.py."""
    from urllib.parse import urlparse

    def _fake_validate(url: str) -> str:
        return (urlparse(url).hostname or "").lower()

    with patch.object(ce_mod, "_validate_public_url", side_effect=_fake_validate):
        yield


def _fake_get(url: str, timeout: int = 10) -> str:
    return HTML_A if "a.example.com" in url else HTML_B


class TestGatherMarketIntelligence:
    def test_aggregates_only_observed_offers(self):
        with patch.object(ce_mod, "_bounded_get", side_effect=_fake_get):
            report = mod.gather_market_intelligence(
                "portable espresso maker", context=SidecarContext(dry_run=False),
                competitor_urls=["https://a.example.com/p", "https://b.example.com/p"],
            )
        assert report.observed_competitor_count == 2
        assert report.observed_median_price == 29.75
        assert report.observed_min_price == 27.5
        assert report.observed_max_price == 32.0
        assert report.observed_rating_mean == 4.05
        assert report.observed_brand_diversity == 1.0  # 2 distinct brands / 2 offers
        assert report.confidence > 0.0

    def test_no_urls_returns_empty_report_with_warning(self):
        report = mod.gather_market_intelligence("x", context=SidecarContext(dry_run=False), competitor_urls=[])
        assert report.observed_competitor_count == 0
        assert report.observed_median_price is None
        assert "no_competitor_urls" in report.warnings[0]

    def test_dry_run_never_performs_network_io(self):
        with patch.object(ce_mod, "_bounded_get", side_effect=AssertionError("must not fetch in dry-run")):
            report = mod.gather_market_intelligence(
                "x", context=SidecarContext(dry_run=True), competitor_urls=["https://a.example.com/p"],
            )
        assert report.observed_competitor_count == 0
        assert all(offer.confidence == 0.0 for offer in report.offers)

    def test_degraded_pages_do_not_fabricate_pricing(self):
        with patch.object(ce_mod, "_bounded_get", return_value=NO_PRODUCT_HTML):
            report = mod.gather_market_intelligence(
                "x", context=SidecarContext(dry_run=False), competitor_urls=["https://a.example.com/p"],
            )
        assert report.observed_median_price is None
        assert report.observed_competitor_count == 0
        assert report.confidence == 0.0

    def test_max_competitors_bounds_url_count(self):
        with patch.object(ce_mod, "_bounded_get", side_effect=_fake_get):
            report = mod.gather_market_intelligence(
                "x", context=SidecarContext(dry_run=False),
                competitor_urls=["https://a.example.com/1", "https://a.example.com/2", "https://a.example.com/3"],
                max_competitors=2,
            )
        assert len(report.offers) == 2

    def test_saturation_increases_with_more_priced_competitors(self):
        with patch.object(ce_mod, "_bounded_get", side_effect=_fake_get):
            few = mod.gather_market_intelligence(
                "x", context=SidecarContext(dry_run=False), competitor_urls=["https://a.example.com/1"],
            )
            many_urls = [f"https://a.example.com/{i}" for i in range(10)]
            many = mod.gather_market_intelligence("x", context=SidecarContext(dry_run=False), competitor_urls=many_urls)
        assert many.market_saturation > few.market_saturation

    def test_deterministic_given_identical_inputs(self):
        with patch.object(ce_mod, "_bounded_get", side_effect=_fake_get):
            first = mod.gather_market_intelligence(
                "x", context=SidecarContext(dry_run=False), competitor_urls=["https://a.example.com/1"], generated_at=1.0,
            )
            second = mod.gather_market_intelligence(
                "x", context=SidecarContext(dry_run=False), competitor_urls=["https://a.example.com/1"], generated_at=1.0,
            )
        assert first.to_dict()["observed_median_price"] == second.to_dict()["observed_median_price"]
        assert first.generated_at == second.generated_at == 1.0


class TestComputeMarginIntelligence:
    def test_full_margin_when_both_inputs_observed(self):
        with patch.object(ce_mod, "_bounded_get", side_effect=_fake_get):
            report = mod.gather_market_intelligence(
                "x", context=SidecarContext(dry_run=False), competitor_urls=["https://a.example.com/1", "https://b.example.com/1"],
            )
        evidence = SupplierEvidenceResult(attempted=True, unit_cost=9.5, shipping_cost=2.0, source_url="https://cj.example/x")
        margin = mod.compute_margin_intelligence("cand-1", supplier_evidence=evidence, market_report=report)
        assert margin.observed_gross_margin is not None
        assert margin.observed_gross_margin > 0
        assert margin.observed_supplier_advantage is not None
        assert margin.provenance == {"supplier_cost": "observed", "market_price": "observed"}
        assert margin.warnings == ()

    def test_missing_supplier_cost_degrades_honestly(self):
        with patch.object(ce_mod, "_bounded_get", side_effect=_fake_get):
            report = mod.gather_market_intelligence(
                "x", context=SidecarContext(dry_run=False), competitor_urls=["https://a.example.com/1"],
            )
        margin = mod.compute_margin_intelligence("cand-1", supplier_evidence=None, market_report=report)
        assert margin.observed_gross_margin is None
        assert margin.observed_margin_confidence == 0.0
        assert "no_observed_supplier_cost" in margin.warnings[0]

    def test_missing_market_report_degrades_honestly(self):
        evidence = SupplierEvidenceResult(attempted=True, unit_cost=9.5, shipping_cost=2.0, source_url="https://cj.example/x")
        margin = mod.compute_margin_intelligence("cand-1", supplier_evidence=evidence, market_report=None)
        assert margin.observed_gross_margin is None
        assert any("no_observed_market_price" in w for w in margin.warnings)

    def test_never_raises_with_both_missing(self):
        margin = mod.compute_margin_intelligence("cand-1", supplier_evidence=None, market_report=None)
        assert margin.observed_gross_margin is None
        assert margin.observed_margin_confidence == 0.0


class TestBuildMarketOpportunityReport:
    def test_full_evidence_recommends_advance(self):
        with patch.object(ce_mod, "_bounded_get", side_effect=_fake_get):
            report = mod.gather_market_intelligence(
                "x", context=SidecarContext(dry_run=False), competitor_urls=["https://a.example.com/1", "https://b.example.com/1"],
            )
        evidence = SupplierEvidenceResult(attempted=True, unit_cost=9.5, shipping_cost=2.0, source_url="https://cj.example/x")
        margin = mod.compute_margin_intelligence("cand-1", supplier_evidence=evidence, market_report=report)
        opp_report = mod.build_market_opportunity_report(
            "cand-1", "Portable Espresso Maker", supplier_evidence=evidence, market_report=report, margin=margin,
        )
        assert opp_report.observed_supplier_cost == 9.5
        assert opp_report.recommended_next_step in {"advance_to_manual_review", "corroborate_before_advancing"}
        assert "supplier_cost" not in opp_report.missing_evidence

    def test_no_evidence_recommends_gathering_more(self):
        opp_report = mod.build_market_opportunity_report("cand-1", "Widget")
        assert opp_report.recommended_next_step == "gather_more_evidence_before_any_decision"
        assert "supplier_cost" in opp_report.missing_evidence
        assert "competitor_evidence" in opp_report.missing_evidence
        assert opp_report.operator_actions

    def test_thin_margin_is_a_risk(self):
        with patch.object(ce_mod, "_bounded_get", side_effect=_fake_get):
            report = mod.gather_market_intelligence(
                "x", context=SidecarContext(dry_run=False), competitor_urls=["https://a.example.com/1"],
            )
        evidence = SupplierEvidenceResult(attempted=True, unit_cost=31.0, shipping_cost=0.0, source_url="https://cj.example/x")
        margin = mod.compute_margin_intelligence("cand-1", supplier_evidence=evidence, market_report=report)
        opp_report = mod.build_market_opportunity_report(
            "cand-1", "Widget", supplier_evidence=evidence, market_report=report, margin=margin,
        )
        assert any("gross margin" in risk.lower() or "margin" in risk for risk in opp_report.market_risks)

    def test_to_dict_json_safe(self):
        opp_report = mod.build_market_opportunity_report("cand-1", "Widget")
        payload = opp_report.to_dict()
        assert payload["candidate_id"] == "cand-1"
        assert isinstance(payload["missing_evidence"], list)


class TestCompetitionIntelligenceEvents:
    def test_emits_expected_event_types(self):
        with patch.object(ce_mod, "_bounded_get", side_effect=_fake_get):
            report = mod.gather_market_intelligence(
                "x", context=SidecarContext(dry_run=False), competitor_urls=["https://a.example.com/1", "https://b.example.com/1"],
                generated_at=1_700_000_000.0,
            )
        evidence = SupplierEvidenceResult(attempted=True, unit_cost=9.5, shipping_cost=2.0, source_url="https://cj.example/x")
        margin = mod.compute_margin_intelligence("cand-1", supplier_evidence=evidence, market_report=report)
        opp_report = mod.build_market_opportunity_report(
            "cand-1", "Widget", supplier_evidence=evidence, market_report=report, margin=margin,
        )
        events = mod.competition_intelligence_events(report, margin, opp_report, workspace_id="ws", run_id="run-1")
        types = [e.event_type for e in events]
        assert types == ["competition_observed", "competition_observed", "competition_summary_created",
                          "market_pricing_computed", "market_intelligence_completed"]
        assert all(isinstance(e, Event) for e in events)

    def test_events_carry_advisory_metadata(self):
        report = mod.gather_market_intelligence("x", context=SidecarContext(dry_run=False), competitor_urls=[], generated_at=1.0)
        events = mod.competition_intelligence_events(report, None, None, workspace_id="ws", run_id="run-1")
        assert len(events) == 1  # only competition_summary_created, no offers/margin/report
        for event in events:
            assert event.metadata["dry_run"] is True
            assert event.metadata["advisory"] is True
            assert event.metadata["no_launch_authority"] is True
            assert event.metadata["no_spend_authority"] is True
            assert event.metadata["no_order_authority"] is True

    def test_events_correlate_to_run_id(self):
        report = mod.gather_market_intelligence("x", context=SidecarContext(dry_run=False), competitor_urls=[], generated_at=1.0)
        events = mod.competition_intelligence_events(report, None, None, workspace_id="ws", run_id="run-42")
        assert all(e.correlation_id == "run-42" for e in events)

    def test_deterministic_event_ids(self):
        report = mod.gather_market_intelligence("x", context=SidecarContext(dry_run=False), competitor_urls=[], generated_at=1.0)
        first = mod.competition_intelligence_events(report, None, None, workspace_id="ws", run_id="run-1")
        second = mod.competition_intelligence_events(report, None, None, workspace_id="ws", run_id="run-1")
        assert [e.event_id for e in first] == [e.event_id for e in second]
