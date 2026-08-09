"""Tests for api.routes.storefront — brand landing pages (TestClient, offline)."""
import pytest
from fastapi.testclient import TestClient

from backend.commerce.brands import Brand
from backend.commerce.catalog import STATUS_LIVE, STATUS_PAUSED, CatalogEntry


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch, tmp_path):
    import backend.core.persistence as pers
    monkeypatch.setattr(pers, "STATE_DIR", str(tmp_path))
    yield


@pytest.fixture
def client(monkeypatch):
    # Fresh registry/catalog wired into the modules the routes import from.
    from backend.commerce.brands import BrandRegistry
    from backend.commerce.catalog import ProductCatalog
    import backend.commerce.brands as brands_mod
    import backend.commerce.catalog as cat_mod

    registry = BrandRegistry()
    catalog = ProductCatalog()
    monkeypatch.setattr(brands_mod, "brand_registry", registry)
    monkeypatch.setattr(cat_mod, "product_catalog", catalog)

    registry.upsert(Brand(brand_id="beauty", name="Beauty Collective",
                          category="beauty", tagline="Curated glow."))
    catalog.register(CatalogEntry(
        product_id="jade-roller", brand_id="beauty", title="Jade Roller",
        retail_price=19.99, status=STATUS_LIVE,
        description_html="<p>Cooling facial massage.</p>",
        bullets=["Natural jade", "Reduces puffiness"],
    ))
    catalog.register(CatalogEntry(
        product_id="paused-item", brand_id="beauty", title="Paused",
        retail_price=9.99, status=STATUS_PAUSED,
    ))

    from backend.api import app
    return TestClient(app)


def test_brand_page_renders_live_products(client):
    resp = client.get("/s/beauty")
    assert resp.status_code == 200
    assert "Beauty Collective" in resp.text
    assert "Jade Roller" in resp.text
    assert "Paused" not in resp.text  # paused products hidden


def test_product_page_renders(client):
    resp = client.get("/s/beauty/jade-roller")
    assert resp.status_code == 200
    assert "Jade Roller" in resp.text
    assert "$19.99" in resp.text
    assert "Natural jade" in resp.text
    assert "/s/beauty/jade-roller/checkout" in resp.text


def test_product_page_threads_utm_into_checkout(client):
    resp = client.get("/s/beauty/jade-roller?utm_source=tiktok&utm_campaign=c1&other=x")
    assert resp.status_code == 200
    assert "utm_source=tiktok" in resp.text
    assert "utm_campaign=c1" in resp.text
    assert "other=x" not in resp.text  # non-utm params not propagated


def test_unknown_brand_404(client):
    assert client.get("/s/nope").status_code == 404
    assert client.get("/s/nope/product").status_code == 404


def test_paused_product_404(client):
    assert client.get("/s/beauty/paused-item").status_code == 404


def test_cross_brand_product_404(client):
    # jade-roller belongs to beauty; accessing under another brand must 404
    from backend.commerce.brands import Brand
    import backend.commerce.brands as brands_mod
    brands_mod.brand_registry.upsert(
        Brand(brand_id="sports", name="Sports Co", category="sports"))
    assert client.get("/s/sports/jade-roller").status_code == 404
