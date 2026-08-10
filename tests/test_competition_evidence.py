"""Tests for backend.adapters.research.competition_evidence."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.adapters.research import competition_evidence as mod
from backend.contracts.adapters import SidecarContext

JSONLD_PRODUCT_HTML = """
<html><head>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "Product", "name": "Portable Espresso Maker",
 "brand": {"name": "AcmeBrand"},
 "aggregateRating": {"ratingValue": "4.5", "reviewCount": "128"},
 "image": ["https://example.com/img.jpg"],
 "offers": {"price": "29.99", "priceCurrency": "USD", "availability": "InStock",
            "seller": {"name": "Acme Store"},
            "shippingDetails": {"shippingRate": {"value": "4.99"}}}}
</script>
</head><body>Product page</body></html>
"""

NO_PRODUCT_HTML = "<html><body><p>Just a page with no structured data.</p></body></html>"

_real_check_robots = mod._check_robots


@pytest.fixture(autouse=True)
def _clear_cache():
    mod._CACHE.clear()
    yield
    mod._CACHE.clear()


@pytest.fixture(autouse=True)
def _no_real_robots_fetch():
    with patch.object(mod, "_check_robots", return_value=None):
        yield


class TestUrlSafety:
    def test_rejects_non_http_scheme(self):
        with pytest.raises(ValueError):
            mod._validate_public_url("ftp://example.com/product/x")

    def test_rejects_no_hostname(self):
        with pytest.raises(ValueError):
            mod._validate_public_url("https:///product/x")

    def test_rejects_private_ip_literal(self):
        with pytest.raises(PermissionError):
            mod._validate_public_url("http://169.254.169.254/latest/meta-data/")

    def test_rejects_loopback(self):
        with pytest.raises(PermissionError):
            mod._validate_public_url("http://127.0.0.1/product/x")

    def test_accepts_arbitrary_public_host_no_fixed_allowlist(self):
        # Unlike cj_public_evidence, this module supports any public
        # storefront domain an operator supplies — no ALLOWED_HOSTS.
        assert mod._validate_public_url("https://example.com/product/x") == "example.com"

    def test_fetch_competitor_offer_degrades_on_rejected_url(self):
        offer = mod.fetch_competitor_offer("http://127.0.0.1/product/x", context=SidecarContext(dry_run=False))
        assert offer.confidence == 0.0
        assert all(status == "missing" for status in offer.field_status.values())
        assert offer.warnings[0].startswith("rejected:")


class TestDryRunGate:
    def test_dry_run_never_performs_network_io(self):
        with patch.object(mod, "_bounded_get", side_effect=AssertionError("must not be called in dry-run")):
            offer = mod.fetch_competitor_offer("https://example.com/product/x", context=SidecarContext(dry_run=True))
        assert offer.warnings == ("dry_run_simulated",)
        assert offer.extraction_method == "simulated"


class TestJsonLdExtraction:
    def test_extracts_observed_fields_including_competition_specific_ones(self):
        with patch.object(mod, "_bounded_get", return_value=JSONLD_PRODUCT_HTML):
            offer = mod.fetch_competitor_offer("https://example.com/product/espresso.html", context=SidecarContext(dry_run=False))
        assert offer.title == "Portable Espresso Maker"
        assert offer.price == 29.99
        assert offer.brand == "AcmeBrand"
        assert offer.seller == "Acme Store"
        assert offer.rating == 4.5
        assert offer.review_count == 128
        assert offer.shipping_cost == 4.99
        assert offer.image == "https://example.com/img.jpg"
        assert offer.field_status["price"] == "observed"
        assert offer.field_status["rating"] == "observed"
        assert offer.field_status["variant_count"] == "missing"
        assert offer.confidence > 0.0

    def test_page_without_structured_data_degrades_honestly(self):
        with patch.object(mod, "_bounded_get", return_value=NO_PRODUCT_HTML):
            offer = mod.fetch_competitor_offer("https://example.com/product/missing.html", context=SidecarContext(dry_run=False))
        assert offer.title == ""
        assert offer.price is None
        assert all(status == "missing" for status in offer.field_status.values())
        assert "no_structured_product_data_found" in offer.warnings

    def test_malformed_jsonld_does_not_raise(self):
        html = '<script type="application/ld+json">{not valid json</script>'
        with patch.object(mod, "_bounded_get", return_value=html):
            offer = mod.fetch_competitor_offer("https://example.com/product/broken.html", context=SidecarContext(dry_run=False))
        assert offer.price is None
        assert offer.confidence == 0.0

    def test_never_invents_a_price_when_page_shows_none(self):
        html = '<script type="application/ld+json">{"@type": "Product", "name": "Widget"}</script>'
        with patch.object(mod, "_bounded_get", return_value=html):
            offer = mod.fetch_competitor_offer("https://example.com/product/widget.html", context=SidecarContext(dry_run=False))
        assert offer.price is None
        assert offer.field_status["price"] == "missing"
        assert "price_not_found_in_structured_data" in offer.warnings

    def test_never_fabricates_variant_count(self):
        # No general schema.org Product signal reliably exposes variant
        # count for a single listing page; this must never be guessed.
        with patch.object(mod, "_bounded_get", return_value=JSONLD_PRODUCT_HTML):
            offer = mod.fetch_competitor_offer("https://example.com/product/espresso.html", context=SidecarContext(dry_run=False))
        assert offer.variant_count is None
        assert offer.field_status["variant_count"] == "missing"


class TestSourceLabeling:
    def test_explicit_source_hint_is_used(self):
        with patch.object(mod, "_bounded_get", return_value=NO_PRODUCT_HTML):
            offer = mod.fetch_competitor_offer("https://example.com/x", source="etsy", context=SidecarContext(dry_run=False))
        assert offer.source == "etsy"

    def test_known_host_label_inferred_without_hint(self):
        with patch.object(mod, "_bounded_get", return_value=NO_PRODUCT_HTML):
            offer = mod.fetch_competitor_offer("https://www.etsy.com/x", context=SidecarContext(dry_run=False))
        assert offer.source == "etsy"

    def test_unknown_host_labeled_generic(self):
        with patch.object(mod, "_bounded_get", return_value=NO_PRODUCT_HTML):
            offer = mod.fetch_competitor_offer("https://example.com/x", context=SidecarContext(dry_run=False))
        assert offer.source == "public_storefront"


class TestRedirectAndSizeSafety:
    def test_redirect_response_is_rejected(self):
        with patch("requests.get") as mock_get:
            mock_get.return_value.status_code = 302
            offer = mod.fetch_competitor_offer("https://example.com/x", context=SidecarContext(dry_run=False))
        assert offer.warnings[0].startswith("fetch_failed:")

    def test_oversized_response_is_rejected(self):
        with patch("requests.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.raise_for_status.return_value = None
            mock_get.return_value.iter_content.return_value = [b"x" * (mod.MAX_RESPONSE_BYTES + 1)]
            offer = mod.fetch_competitor_offer("https://example.com/x", context=SidecarContext(dry_run=False))
        assert offer.warnings[0].startswith("fetch_failed:")


class TestCaching:
    def test_second_fetch_uses_cache_not_network(self):
        with patch.object(mod, "_bounded_get", return_value=JSONLD_PRODUCT_HTML) as mock_get:
            mod.fetch_competitor_offer("https://example.com/product/espresso.html", context=SidecarContext(dry_run=False))
            mod.fetch_competitor_offer("https://example.com/product/espresso.html", context=SidecarContext(dry_run=False))
        assert mock_get.call_count == 1


class TestRobotsEnforcement:
    def test_robots_disallow_blocks_fetch(self):
        class _StubRobots:
            def read(self):
                pass

            def can_fetch(self, agent, url):
                return False

        with patch("urllib.robotparser.RobotFileParser", return_value=_StubRobots()):
            with pytest.raises(PermissionError):
                _real_check_robots("example.com", "https://example.com/product/x")

    def test_unreadable_robots_blocks_fetch(self):
        class _StubRobots:
            def read(self):
                raise OSError("network unavailable")

        with patch("urllib.robotparser.RobotFileParser", return_value=_StubRobots()):
            with pytest.raises(PermissionError):
                _real_check_robots("example.com", "https://example.com/product/x")

    def test_robots_allow_permits_fetch(self):
        class _StubRobots:
            def read(self):
                pass

            def can_fetch(self, agent, url):
                return True

        with patch("urllib.robotparser.RobotFileParser", return_value=_StubRobots()):
            _real_check_robots("example.com", "https://example.com/product/x")  # does not raise


class TestScoreOffers:
    def test_ranks_by_relevance_completeness_confidence(self):
        with patch.object(mod, "_bounded_get", return_value=JSONLD_PRODUCT_HTML):
            good = mod.fetch_competitor_offer("https://example.com/good", context=SidecarContext(dry_run=False))
        bad_html = '<script type="application/ld+json">{"@type": "Product", "name": "Unrelated Gadget"}</script>'
        with patch.object(mod, "_bounded_get", return_value=bad_html):
            bad = mod.fetch_competitor_offer("https://example.com/bad", context=SidecarContext(dry_run=False))
        ranked = mod.score_offers([bad, good], "portable espresso maker")
        assert ranked[0]["listing_id"] == good.external_listing_id
        assert ranked[0]["composite_score"] >= ranked[1]["composite_score"]

    def test_empty_offers_returns_empty_ranking(self):
        assert mod.score_offers([], "anything") == []


class TestHealth:
    def test_health_reports_not_reachable_in_this_sandbox(self):
        health = mod.health()
        assert health.configured is True
        assert health.reachable is False
        assert "jsonld_extraction" in health.capabilities
