"""Tests for backend.commerce — brand registry, catalog, storefront adapters."""
import pytest

from backend.commerce.brands import Brand, BrandRegistry
from backend.commerce.catalog import (
    STATUS_LIVE,
    STATUS_PAUSED,
    CatalogEntry,
    ProductCatalog,
    product_slug,
)
from backend.commerce.storefront import LandingStorefront, get_storefront


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch, tmp_path):
    """Point all snapshot writes at a private temp dir."""
    import backend.core.persistence as pers
    monkeypatch.setattr(pers, "STATE_DIR", str(tmp_path))
    yield


@pytest.fixture
def registry():
    r = BrandRegistry()
    yield r
    r.reset()


@pytest.fixture
def catalog(monkeypatch):
    c = ProductCatalog()
    # Route module-singleton access (used inside storefront adapters) to this instance.
    import backend.commerce.catalog as cat_mod
    monkeypatch.setattr(cat_mod, "product_catalog", c)
    import backend.commerce.storefront as sf_mod
    monkeypatch.setattr(sf_mod, "product_catalog", c)
    yield c
    c.reset()


class TestBrandRegistry:
    def test_ensure_default_seeds_general_brand(self, registry):
        brand = registry.ensure_default()
        assert brand.brand_id == "default"
        assert brand.category == "general"
        assert registry.get("default") is not None

    def test_resolve_creates_category_brand(self, registry):
        brand = registry.resolve_for_category("beauty")
        assert brand.brand_id == "beauty"
        assert brand.category == "beauty"
        # Second resolve returns the same brand, no duplicate
        again = registry.resolve_for_category("beauty")
        assert again.brand_id == brand.brand_id
        assert len(registry.all()) == 1

    def test_max_brands_cap_routes_to_default(self, registry, monkeypatch):
        import backend.commerce.brands as brands_mod
        monkeypatch.setattr(brands_mod, "_MAX_BRANDS", 2)

        registry.resolve_for_category("beauty")
        registry.resolve_for_category("electronics")
        overflow = registry.resolve_for_category("sports")
        assert overflow.brand_id == "default"
        # sports is remembered as owned by default (no churn on re-resolve)
        assert registry.resolve_for_category("sports").brand_id == "default"

    def test_general_category_goes_to_default(self, registry):
        brand = registry.resolve_for_category("general")
        assert brand.brand_id == "default"

    def test_snapshot_restore_roundtrip(self, registry):
        registry.resolve_for_category("beauty")
        snap = registry.snapshot()

        fresh = BrandRegistry()
        fresh.restore(snap)
        assert fresh.get("beauty") is not None
        assert fresh.resolve_for_category("beauty").brand_id == "beauty"


class TestProductCatalog:
    def test_register_and_get(self, catalog):
        entry = CatalogEntry(product_id="widget", brand_id="default",
                             title="Widget", retail_price=19.99)
        catalog.register(entry)
        assert catalog.get("widget").title == "Widget"

    def test_update_fields_and_reject_bad_status(self, catalog):
        catalog.register(CatalogEntry(product_id="widget", brand_id="default",
                                      title="Widget", retail_price=19.99))
        catalog.update("widget", retail_price=24.99, status="bogus")
        entry = catalog.get("widget")
        assert entry.retail_price == 24.99
        assert entry.status == "draft"  # invalid status ignored
        catalog.update("widget", status=STATUS_PAUSED)
        assert catalog.get("widget").status == STATUS_PAUSED

    def test_for_brand_filters(self, catalog):
        catalog.register(CatalogEntry(product_id="a", brand_id="b1",
                                      title="A", retail_price=1.0, status=STATUS_LIVE))
        catalog.register(CatalogEntry(product_id="b", brand_id="b2",
                                      title="B", retail_price=1.0, status=STATUS_LIVE))
        assert [e.product_id for e in catalog.for_brand("b1")] == ["a"]
        assert [e.product_id for e in catalog.for_brand("b1", status=STATUS_LIVE)] == ["a"]

    def test_product_slug(self):
        assert product_slug("Wireless Earbuds Pro!") == "wireless-earbuds-pro"


class TestLandingStorefront:
    def test_create_product_registers_catalog_entry(self, catalog):
        brand = Brand(brand_id="beauty", name="Beauty Co", category="beauty")
        sf = LandingStorefront()
        result = sf.create_product(
            brand,
            {"title": "Collagen Serum", "description": "<p>Glow.</p>",
             "bullets": ["hydrating", "vegan"]},
            29.99,
            supplier={"supplier": "cjdropshipping", "product_id": "cj_123",
                      "landed_cost": 8.5},
        )
        assert result["status"] == "ok"
        assert "/s/beauty/collagen-serum" in result["url"]
        entry = catalog.get("collagen-serum")
        assert entry.status == STATUS_LIVE
        assert entry.supplier == "cjdropshipping"
        assert entry.landed_cost == 8.5

    def test_update_product(self, catalog):
        brand = Brand(brand_id="beauty", name="Beauty Co", category="beauty")
        sf = LandingStorefront()
        sf.create_product(brand, {"title": "Serum"}, 20.0)
        result = sf.update_product(brand, "serum", price=25.0, stock_ok=False)
        assert result["status"] == "ok"
        assert catalog.get("serum").retail_price == 25.0
        assert catalog.get("serum").stock_ok is False

    def test_update_unknown_product_errors(self, catalog):
        brand = Brand(brand_id="beauty", name="Beauty Co", category="beauty")
        result = LandingStorefront().update_product(brand, "nope", price=1.0)
        assert result["status"] == "error"


class TestStorefrontDispatch:
    def test_landing_default(self):
        brand = Brand(brand_id="x", name="X", category="x")
        assert isinstance(get_storefront(brand), LandingStorefront)

    def test_unknown_binding_falls_back_to_landing(self):
        brand = Brand(brand_id="x", name="X", category="x", storefront="weird")
        assert isinstance(get_storefront(brand), LandingStorefront)


class TestBuildProductBrandRouting:
    def test_build_product_routes_to_brand(self, registry, catalog, monkeypatch):
        import backend.commerce.brands as brands_mod
        monkeypatch.setattr(brands_mod, "brand_registry", registry)
        import backend.creation.store_builder  # noqa: F401 — uses lazy import inside fn

        from backend.creation.store_builder import build_product
        verdict = {
            "product": "Jade Roller",
            "ready_for_creation": True,
            "category": "beauty",
            "suggested_price": 19.99,
            "supplier": {"supplier": "spocket", "product_id": "sp_9",
                         "fulfillment_days": 7, "landed_cost": 6.0},
        }
        result = build_product(verdict)
        assert result["status"] == "ok"
        assert result["brand_id"] == "beauty"
        entry = catalog.get(product_slug(result["listing"]["title"]))
        assert entry is not None
        assert entry.brand_id == "beauty"
