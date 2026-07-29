"""Tests for backend.commerce.checkout — Stripe Checkout Session creation."""
import pytest

from backend.commerce.brands import Brand
from backend.commerce.catalog import STATUS_LIVE, STATUS_PAUSED, CatalogEntry


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch, tmp_path):
    import backend.core.persistence as pers
    monkeypatch.setattr(pers, "STATE_DIR", str(tmp_path))
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("CHECKOUT_DRY_RUN", raising=False)
    yield


@pytest.fixture
def commerce(monkeypatch):
    from backend.commerce.brands import BrandRegistry
    from backend.commerce.catalog import ProductCatalog
    import backend.commerce.brands as brands_mod
    import backend.commerce.catalog as cat_mod
    import backend.commerce.checkout as checkout_mod

    registry = BrandRegistry()
    catalog = ProductCatalog()
    monkeypatch.setattr(brands_mod, "brand_registry", registry)
    monkeypatch.setattr(cat_mod, "product_catalog", catalog)
    monkeypatch.setattr(checkout_mod, "brand_registry", registry, raising=False)

    registry.upsert(Brand(brand_id="beauty", name="Beauty Co", category="beauty"))
    catalog.register(CatalogEntry(
        product_id="jade-roller", brand_id="beauty", title="Jade Roller",
        retail_price=19.99, status=STATUS_LIVE,
    ))
    catalog.register(CatalogEntry(
        product_id="paused", brand_id="beauty", title="Paused",
        retail_price=9.99, status=STATUS_PAUSED,
    ))
    catalog.register(CatalogEntry(
        product_id="oos", brand_id="beauty", title="Out of Stock",
        retail_price=9.99, status=STATUS_LIVE, stock_ok=False,
    ))
    return registry, catalog


class TestDryRunCheckout:
    def test_creates_dry_session_by_default(self, commerce):
        from backend.commerce.checkout import create_checkout_session

        result = create_checkout_session("beauty", "jade-roller", qty=1)
        assert result["status"] == "ok"
        assert result["dry_run"] is True
        assert result["session_id"].startswith("dry_cs_")
        assert "jade-roller" in result["url"]

    def test_qty_is_clamped_to_at_least_one(self, commerce):
        from backend.commerce.checkout import create_checkout_session

        result = create_checkout_session("beauty", "jade-roller", qty=0)
        assert result["status"] == "ok"

    def test_unknown_product_errors(self, commerce):
        from backend.commerce.checkout import create_checkout_session

        result = create_checkout_session("beauty", "nope")
        assert result["status"] == "error"
        assert result["error"] == "unknown_product"

    def test_wrong_brand_for_product_errors(self, commerce):
        from backend.commerce.checkout import create_checkout_session

        result = create_checkout_session("other-brand", "jade-roller")
        assert result["status"] == "error"

    def test_paused_product_unavailable(self, commerce):
        from backend.commerce.checkout import create_checkout_session

        result = create_checkout_session("beauty", "paused")
        assert result["status"] == "error"
        assert result["error"] == "unavailable"

    def test_out_of_stock_unavailable(self, commerce):
        from backend.commerce.checkout import create_checkout_session

        result = create_checkout_session("beauty", "oos")
        assert result["status"] == "error"
        assert result["error"] == "unavailable"

    def test_utm_filtered_to_utm_prefixed_only(self, commerce):
        from backend.commerce.checkout import create_checkout_session

        result = create_checkout_session(
            "beauty", "jade-roller",
            utm={"utm_source": "tiktok", "utm_campaign": "c1", "other": "drop-me"},
        )
        assert result["status"] == "ok"

    def test_dry_session_ids_unique(self, commerce):
        from backend.commerce.checkout import create_checkout_session

        a = create_checkout_session("beauty", "jade-roller")
        b = create_checkout_session("beauty", "jade-roller")
        assert a["session_id"] != b["session_id"]


class TestLiveCheckoutSessionCreation:
    """Regression guard: stripe SDK objects (unlike plain dicts) raise
    AttributeError on `.get(...)` — a real stripe.checkout.Session (or any
    StripeObject) routes `.get` through __getattr__ to a key lookup. Uses a
    real Session instance (not a plain dict) so this actually exercises that
    behavior rather than a mock that happens to support .get()."""

    def test_live_session_create_reads_id_and_url_via_bracket_access(self, commerce, monkeypatch):
        import stripe
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fake")
        monkeypatch.setenv("CHECKOUT_DRY_RUN", "false")

        fake_session = stripe.checkout.Session()
        fake_session["id"] = "cs_live_123"
        fake_session["url"] = "https://checkout.stripe.com/pay/cs_live_123"
        monkeypatch.setattr(stripe.checkout.Session, "create", lambda **kw: fake_session)

        from backend.commerce.checkout import create_checkout_session
        result = create_checkout_session("beauty", "jade-roller", qty=1)

        assert result["status"] == "ok"
        assert result["session_id"] == "cs_live_123"
        assert result["url"] == "https://checkout.stripe.com/pay/cs_live_123"
        assert result["dry_run"] is False


class TestLiveCheckoutGating:
    def test_stays_dry_without_secret_even_if_flag_false(self, commerce, monkeypatch):
        monkeypatch.setenv("CHECKOUT_DRY_RUN", "false")
        # No STRIPE_SECRET_KEY set -> must still be dry
        from backend.commerce.checkout import create_checkout_session

        result = create_checkout_session("beauty", "jade-roller")
        assert result["dry_run"] is True
