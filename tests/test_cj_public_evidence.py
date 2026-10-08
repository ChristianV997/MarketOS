"""Tests for backend.adapters.research.cj_public_evidence."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.adapters.research import cj_public_evidence as mod
from backend.contracts.adapters import SidecarContext
from backend.mvp_commerce.supplier_evidence import SupplierEvidenceResult, supplier_evidence_events
from evaluation.contracts import DataQuality, ProductCandidate
from evaluation.readiness import evaluate_product

JSONLD_PRODUCT_HTML = """
<html><head>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "Product", "name": "Portable Espresso Maker",
 "sku": "CJ-ESP-001", "description": "Compact travel espresso maker.",
 "offers": {"price": "9.50", "priceCurrency": "USD", "availability": "InStock"}}
</script>
</head><body>Product page</body></html>
"""

NO_PRODUCT_HTML = "<html><body><p>Just a page with no structured data.</p></body></html>"
JSONLD_MISSING_PRICE_HTML = '''<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "Product", "name": "Unpriced Widget", "sku": "CJ-NO-PRICE"}
</script>'''

# Captured before the autouse fixture below patches mod._check_robots, so
# TestRobotsEnforcement can still exercise the real implementation.
_real_check_robots = mod._check_robots


@pytest.fixture(autouse=True)
def _clear_cache():
    mod._CACHE.clear()
    yield
    mod._CACHE.clear()


@pytest.fixture(autouse=True)
def _no_real_robots_fetch():
    """robots.txt enforcement itself is exercised by TestRobotsEnforcement
    below; every other test targets extraction/caching/scoring/safety and
    must not depend on a real network fetch of cjdropshipping.com/robots.txt
    (which this sandbox's own network policy blocks)."""
    with patch.object(mod, "_check_robots", return_value=None):
        yield


class TestUrlSafety:
    def test_rejects_non_http_scheme(self):
        with pytest.raises(ValueError):
            mod._validate_public_url("ftp://cjdropshipping.com/product/x")

    def test_rejects_disallowed_host(self):
        with pytest.raises(PermissionError):
            mod._validate_public_url("https://evil.example.com/product/x")

    def test_rejects_ip_literal_not_on_allowlist(self):
        with pytest.raises(PermissionError):
            mod._validate_public_url("http://169.254.169.254/latest/meta-data/")

    def test_accepts_allowlisted_host(self):
        assert mod._validate_public_url("https://www.cjdropshipping.com/product/x.html") == "www.cjdropshipping.com"

    def test_fetch_product_evidence_degrades_on_disallowed_host(self):
        evidence = mod.fetch_product_evidence("https://evil.example.com/product/x", context=SidecarContext(dry_run=False))
        assert evidence.confidence == 0.0
        assert all(status == "unavailable" for status in evidence.field_status.values())
        assert evidence.warnings[0].startswith("rejected:")


def _public_dns(*_args, **_kwargs):
    import socket
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 0))]


class TestRequestTargetIsExact:
    def test_suffix_host_not_fetched(self):
        with patch("socket.getaddrinfo", side_effect=_public_dns):
            with patch("requests.get") as get:
                for url in (
                    "https://evil.cjdropshipping.com/product/x",
                    "https://evil.www.cjdropshipping.com/product/x",
                ):
                    with pytest.raises(PermissionError):
                        mod._validate_public_url(url)
                    evidence = mod.fetch_product_evidence(url, context=SidecarContext(dry_run=False))
                    assert evidence.warnings[0].startswith("rejected:")
                get.assert_not_called()

    def test_http_userinfo_and_non_443_port_are_not_fetched(self):
        urls = (
            "http://www.cjdropshipping.com/product/x.html",
            "https://user:pass@www.cjdropshipping.com/product/x",
            "https://@www.cjdropshipping.com/product/x",
            "https://www.cjdropshipping.com:8443/product/x",
            "https://www.cjdropshipping.com:80/product/x",
            "https://127.0.0.1:6379\\@www.cjdropshipping.com/latest/meta-data/",
            "http://127.0.0.1:6379\\@www.cjdropshipping.com/latest/meta-data/",
        )
        with patch("socket.getaddrinfo", side_effect=_public_dns):
            with patch("requests.get") as get:
                with pytest.raises(ValueError):
                    mod._validate_public_url(urls[0])
                for url in urls[1:]:
                    with pytest.raises(PermissionError):
                        mod._validate_public_url(url)
                for url in urls:
                    evidence = mod.fetch_product_evidence(url, context=SidecarContext(dry_run=False))
                    assert evidence.warnings[0].startswith("rejected:")
                get.assert_not_called()

    def test_rebuilt_url_is_what_gets_fetched(self, monkeypatch):
        seen = {}

        class _StubRobots:
            def __init__(self, url):
                seen["robots"] = url

            def read(self):
                return None

            def can_fetch(self, _agent, url):
                seen["page"] = url
                return True

        class _Response:
            status_code = 200

            def raise_for_status(self):
                return None

            def iter_content(self, chunk_size=65536):
                yield JSONLD_PRODUCT_HTML.encode()

        monkeypatch.setattr(mod.robotparser, "RobotFileParser", _StubRobots)
        raw = "https://cjdropshipping.com:443/product/x.html?id=1#frag"
        expected = "https://www.cjdropshipping.com/product/x.html?id=1"
        with patch("socket.getaddrinfo", side_effect=_public_dns):
            with patch("requests.get", return_value=_Response()) as get:
                with patch.object(mod, "_check_robots", _real_check_robots):
                    evidence = mod.fetch_product_evidence(raw, context=SidecarContext(dry_run=False))
                    mod.fetch_product_evidence(expected, context=SidecarContext(dry_run=False))
        assert get.call_count == 1
        assert get.call_args.args[0] == expected
        assert seen["robots"] == "https://www.cjdropshipping.com/robots.txt"
        assert seen["page"] == expected
        assert expected in mod._CACHE
        assert evidence.title == "Portable Espresso Maker"



class TestDryRunGate:
    def test_dry_run_never_performs_network_io(self):
        with patch.object(mod, "_bounded_get", side_effect=AssertionError("must not be called in dry-run")):
            evidence = mod.fetch_product_evidence("https://www.cjdropshipping.com/product/x.html", context=SidecarContext(dry_run=True))
        assert evidence.warnings == ("dry_run_simulated",)
        assert evidence.extraction_method == "simulated"


class TestJsonLdExtraction:
    def test_extracts_observed_fields_from_valid_product_jsonld(self):
        with patch.object(mod, "_bounded_get", return_value=JSONLD_PRODUCT_HTML):
            evidence = mod.fetch_product_evidence(
                "https://www.cjdropshipping.com/product/espresso.html",
                context=SidecarContext(dry_run=False),
            )
        assert evidence.title == "Portable Espresso Maker"
        assert evidence.price == 9.5
        assert evidence.field_status["title"] == "observed"
        assert evidence.field_status["price"] == "observed"
        assert evidence.field_status["weight_kg"] == "unavailable"
        assert evidence.confidence > 0.0

    def test_page_without_structured_data_degrades_honestly(self):
        with patch.object(mod, "_bounded_get", return_value=NO_PRODUCT_HTML):
            evidence = mod.fetch_product_evidence(
                "https://www.cjdropshipping.com/product/missing.html",
                context=SidecarContext(dry_run=False),
            )
        assert evidence.title == ""
        assert evidence.price is None
        assert all(status == "unavailable" for status in evidence.field_status.values())
        assert "no_structured_product_data_found" in evidence.warnings

    def test_malformed_jsonld_does_not_raise(self):
        html = '<script type="application/ld+json">{not valid json</script>'
        with patch.object(mod, "_bounded_get", return_value=html):
            evidence = mod.fetch_product_evidence(
                "https://www.cjdropshipping.com/product/broken.html",
                context=SidecarContext(dry_run=False),
            )
        assert evidence.price is None
        assert evidence.confidence == 0.0

    def test_never_invents_a_price_when_page_shows_none(self):
        html = '<script type="application/ld+json">{"@type": "Product", "name": "Widget"}</script>'
        with patch.object(mod, "_bounded_get", return_value=html):
            evidence = mod.fetch_product_evidence(
                "https://www.cjdropshipping.com/product/widget.html",
                context=SidecarContext(dry_run=False),
            )
        assert evidence.price is None
        assert evidence.field_status["price"] == "unavailable"


class TestOptionalJsRendering:
    def test_js_render_fallback_is_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("MARKETOS_PHASE1_JS_RENDER", raising=False)
        with patch.object(mod, "_bounded_get", return_value=NO_PRODUCT_HTML):
            with patch.object(mod.Crawl4AIResearchAdapter, "discover_sync") as render:
                evidence = mod.fetch_product_evidence(
                    "https://www.cjdropshipping.com/product/static.html",
                    context=SidecarContext(dry_run=False),
                )
        render.assert_not_called()
        assert evidence.warnings == ("no_structured_product_data_found",)

    def test_allowlisted_js_render_fallback_maps_observed_fields(self, monkeypatch):
        monkeypatch.setenv("MARKETOS_PHASE1_JS_RENDER", "1")
        monkeypatch.setenv("CRAWL4AI_ALLOWED_DOMAINS", "www.cjdropshipping.com")
        records = [{
            "name": "Rendered Travel Espresso Maker",
            "product_id": "CJ-RENDERED-001",
            "selling_price": 8.75,
            "currency": "USD",
            "availability": "InStock",
            "description": "Rendered structured product record.",
        }]
        with patch.object(mod, "_bounded_get", return_value=NO_PRODUCT_HTML):
            with patch.object(mod.Crawl4AIResearchAdapter, "discover_sync", return_value=records):
                evidence = mod.fetch_product_evidence(
                    "https://www.cjdropshipping.com/product/rendered.html",
                    context=SidecarContext(dry_run=False),
                )
        assert evidence.title == "Rendered Travel Espresso Maker"
        assert evidence.price == 8.75
        assert evidence.sku == "CJ-RENDERED-001"
        assert evidence.field_status["price"] == "observed"
        assert evidence.extraction_method == "crawl4ai_js_rendered_structured_product"


class TestNetworkFailureDegradation:
    def test_fetch_exception_degrades_without_raising(self):
        with patch.object(mod, "_bounded_get", side_effect=ConnectionError("blocked")):
            evidence = mod.fetch_product_evidence(
                "https://www.cjdropshipping.com/product/x.html",
                context=SidecarContext(dry_run=False),
            )
        assert evidence.confidence == 0.0
        assert evidence.warnings[0].startswith("fetch_failed:")

    def test_response_too_large_is_rejected(self):
        def _oversized(url, timeout=10):
            raise ValueError("cj_evidence_response_too_large")

        with patch.object(mod, "_bounded_get", side_effect=_oversized):
            evidence = mod.fetch_product_evidence(
                "https://www.cjdropshipping.com/product/huge.html",
                context=SidecarContext(dry_run=False),
            )
        assert "fetch_failed:ValueError" in evidence.warnings[0]

    def test_redirect_is_rejected_not_followed(self):
        class _FakeResponse:
            status_code = 302
            headers = {"Location": "https://evil.example.com/"}

        with patch("requests.get", return_value=_FakeResponse()):
            with pytest.raises(PermissionError):
                mod._bounded_get("https://www.cjdropshipping.com/product/x.html")


class TestCaching:
    def test_second_fetch_uses_cache_not_network(self):
        with patch.object(mod, "_bounded_get", return_value=JSONLD_PRODUCT_HTML) as fake_get:
            mod.fetch_product_evidence("https://www.cjdropshipping.com/product/cached.html", context=SidecarContext(dry_run=False))
            mod.fetch_product_evidence("https://www.cjdropshipping.com/product/cached.html", context=SidecarContext(dry_run=False))
        assert fake_get.call_count == 1


class TestNormalization:
    def test_to_supplier_offer_uses_observed_price_and_shipping(self):
        evidence = mod.CJProductEvidence(
            source=mod.SOURCE, source_url="https://www.cjdropshipping.com/product/x.html",
            observed_at=1_700_000_000.0, external_product_id="x", title="Widget",
            field_status={"title": "observed", "price": "observed", "shipping_cost": "observed"},
            price=9.5, shipping_cost=2.25,
        )
        offer = mod.to_supplier_offer(evidence)
        assert offer is not None
        assert offer.unit_cost == 9.5
        assert offer.shipping_cost == 2.25
        assert offer.quality.provenance == "public_page"
        assert offer.quality.is_live_attributed is False
        assert offer.quality.source_ref == evidence.source_url
        assert offer.quality.observed_at.timestamp() == 1_700_000_000.0

    def test_to_supplier_offer_none_without_observed_price(self):
        evidence = mod._degraded("https://www.cjdropshipping.com/product/x.html", reason="test")
        assert mod.to_supplier_offer(evidence) is None

    def test_to_product_candidate_requires_title(self):
        evidence = mod._degraded("https://www.cjdropshipping.com/product/x.html", reason="test")
        assert mod.to_product_candidate(evidence) is None

    def test_missing_price_stays_missing_instead_of_becoming_zero(self):
        url = "https://www.cjdropshipping.com/product/unpriced.html"
        evidence = mod._extract_from_jsonld(JSONLD_MISSING_PRICE_HTML, url)

        assert evidence is not None
        assert evidence.price is None
        assert evidence.field_status["price"] == "unavailable"
        assert mod.to_supplier_offer(evidence) is None
        assert mod.to_product_candidate(evidence) is None

    def test_missing_shipping_is_not_coerced_to_free_shipping(self):
        """SupplierOffer.shipping_cost is a bare float; missing must not become 0.0."""
        evidence = mod.CJProductEvidence(
            source=mod.SOURCE, source_url="https://www.cjdropshipping.com/product/x.html",
            observed_at=1_700_000_000.0, external_product_id="x", title="Widget",
            field_status={"title": "observed", "price": "observed", "shipping_cost": "unavailable"},
            price=9.5, shipping_cost=None,
        )

        assert mod.to_supplier_offer(evidence) is None

    def test_explicit_zero_shipping_is_preserved(self):
        evidence = mod.CJProductEvidence(
            source=mod.SOURCE, source_url="https://www.cjdropshipping.com/product/x.html",
            observed_at=1_700_000_000.0, external_product_id="x", title="Widget",
            field_status={"title": "observed", "price": "observed", "shipping_cost": "observed"},
            price=9.5, shipping_cost=0.0,
        )

        offer = mod.to_supplier_offer(evidence)

        assert offer is not None
        assert offer.shipping_cost == 0.0

    def test_public_page_product_candidate_is_not_live_supplier_proof(self):
        evidence = mod.CJProductEvidence(
            source=mod.SOURCE, source_url="https://www.cjdropshipping.com/product/x.html",
            observed_at=1_700_000_000.0, external_product_id="x", title="Widget",
            field_status={"title": "observed", "price": "observed"}, price=9.5,
        )

        candidate = mod.to_product_candidate(evidence)

        assert candidate is not None
        assert candidate.quality.provenance == "public_page"
        assert candidate.quality.is_live_attributed is False
        assert candidate.quality.completeness == "partial"
        assert candidate.quality.observed_at.timestamp() == 1_700_000_000.0

    def test_public_page_supplier_offer_cannot_satisfy_launch_readiness(self):
        evidence = mod.CJProductEvidence(
            source=mod.SOURCE, source_url="https://www.cjdropshipping.com/product/x.html",
            observed_at=1_700_000_000.0, external_product_id="x", title="Widget",
            field_status={"title": "observed", "price": "observed", "shipping_cost": "observed"},
            price=5.0, shipping_cost=1.0,
        )
        product = ProductCandidate(
            product_id="market-widget", name="Widget", selling_price=100.0,
            quality=DataQuality(provenance="live", attribution="attributed"),
        )
        offer = mod.to_supplier_offer(evidence)

        readiness = evaluate_product(product, offer)

        assert offer is not None
        assert offer.quality.completeness == "partial"
        assert offer.quality.is_live_attributed is False
        assert readiness.launchable is False
        assert "incomplete_data" in readiness.reasons


class TestScoring:
    def test_relevant_and_complete_evidence_ranks_first(self):
        with patch.object(mod, "_bounded_get", return_value=JSONLD_PRODUCT_HTML):
            good = mod.fetch_product_evidence("https://www.cjdropshipping.com/product/good.html", context=SidecarContext(dry_run=False))
        bad = mod._degraded("https://www.cjdropshipping.com/product/bad.html", reason="test")
        ranking = mod.score_candidates([bad, good], "portable espresso maker")
        assert ranking[0]["product_id"] == good.external_product_id
        assert ranking[0]["composite_score"] > ranking[1]["composite_score"]

    def test_missing_fields_never_count_as_favorable(self):
        evidence = mod._degraded("https://www.cjdropshipping.com/product/x.html", reason="test")
        ranking = mod.score_candidates([evidence], "anything")
        assert ranking[0]["composite_score"] == 0.0
        assert len(ranking[0]["missing_evidence"]) == len(mod._EVIDENCE_FIELDS)

    def test_missing_price_and_public_only_scope_survive_scoring(self):
        evidence = mod._extract_from_jsonld(
            JSONLD_MISSING_PRICE_HTML, "https://www.cjdropshipping.com/product/unpriced.html"
        )
        assert evidence is not None

        score = mod.score_candidates([evidence], "unpriced widget")[0]

        assert "price" in score["missing_evidence"]
        assert "price" in score["assumptions_still_required"]
        assert score["evidence_mode"] == "public_page_observation"
        assert score["supplier_live_proof"] is False


def test_supplier_public_evidence_events_have_no_external_authority():
    evidence = mod.CJProductEvidence(
        source=mod.SOURCE, source_url="https://www.cjdropshipping.com/product/x.html",
        observed_at=1.0, external_product_id="x", title="Widget",
        field_status={"title": "observed", "price": "observed"}, price=9.5,
    )
    result = SupplierEvidenceResult(
        attempted=True, unit_cost=9.5, shipping_cost=None, source_url=evidence.source_url,
        evidence=evidence, source_type="public_page_static", status="observed",
    )

    events = supplier_evidence_events(result, workspace_id="ws", run_id="fixture-run", occurred_at=1.0)

    assert all(event.metadata["non_authoritative"] is True for event in events)
    for key in (
        "no_launch_authority", "no_ad_authority", "no_spend_authority",
        "no_order_authority", "no_payment_authority",
    ):
        assert all(event.metadata[key] is True for event in events)


class TestDiscovery:
    def test_discovery_dry_run_returns_empty(self):
        urls = mod.discover_candidate_urls("espresso maker", context=SidecarContext(dry_run=True))
        assert urls == []

    def test_discovery_disallowed_domain_query_still_bounded(self):
        # build_search_url always targets the allowlisted CJ host regardless
        # of query content.
        url = mod.build_search_url("<script>alert(1)</script>")
        assert url.startswith("https://www.cjdropshipping.com/search?keyword=")
        assert "<script>" not in url

    def test_discovery_extracts_product_links(self):
        html = (
            '<a href="https://www.cjdropshipping.com/product/one.html">One</a>'
            '<a href="https://www.cjdropshipping.com/product/two.html">Two</a>'
            '<a href="https://www.cjdropshipping.com/other/page.html">Other</a>'
        )
        with patch.object(mod, "_bounded_get", return_value=html):
            urls = mod.discover_candidate_urls("espresso maker", context=SidecarContext(dry_run=False))
        assert urls == [
            "https://www.cjdropshipping.com/product/one.html",
            "https://www.cjdropshipping.com/product/two.html",
        ]

    def test_discovery_degrades_to_empty_on_failure(self):
        with patch.object(mod, "_bounded_get", side_effect=ConnectionError("blocked")):
            urls = mod.discover_candidate_urls("espresso maker", context=SidecarContext(dry_run=False))
        assert urls == []


def test_health_reports_unverified_reachability():
    health = mod.health()
    assert health.configured is True
    assert health.reachable is False


class TestRobotsEnforcement:
    """Exercises _check_robots directly (bypassing the autouse no-op fixture
    used by every other test) against a stubbed RobotFileParser — no real
    network fetch of a robots.txt file."""

    def test_disallowed_path_raises_permission_error(self, monkeypatch):
        class _StubRobots:
            def __init__(self, url):
                pass

            def read(self):
                pass

            def can_fetch(self, agent, url):
                return False

        monkeypatch.setattr(mod.robotparser, "RobotFileParser", _StubRobots)
        with pytest.raises(PermissionError):
            _real_check_robots("www.cjdropshipping.com", "https://www.cjdropshipping.com/product/blocked.html")

    def test_allowed_path_does_not_raise(self, monkeypatch):
        class _StubRobots:
            def __init__(self, url):
                pass

            def read(self):
                pass

            def can_fetch(self, agent, url):
                return True

        monkeypatch.setattr(mod.robotparser, "RobotFileParser", _StubRobots)
        _real_check_robots("www.cjdropshipping.com", "https://www.cjdropshipping.com/product/ok.html")

    def test_unreadable_robots_txt_blocks_rather_than_proceeds(self, monkeypatch):
        class _StubRobots:
            def __init__(self, url):
                pass

            def read(self):
                raise OSError("network unreachable")

            def can_fetch(self, agent, url):
                return True

        monkeypatch.setattr(mod.robotparser, "RobotFileParser", _StubRobots)
        with pytest.raises(PermissionError):
            _real_check_robots("www.cjdropshipping.com", "https://www.cjdropshipping.com/product/x.html")
