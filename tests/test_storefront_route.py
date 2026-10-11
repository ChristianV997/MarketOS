"""Tests for api.routes.storefront — brand landing pages (ASGI, offline)."""
import asyncio

import pytest

from backend.commerce.brands import Brand
from backend.commerce.catalog import STATUS_LIVE, STATUS_PAUSED, CatalogEntry


class _Response:
    def __init__(self, status_code: int, headers: dict[str, str], body: bytes) -> None:
        self.status_code = status_code
        self.headers = headers
        self.content = body

    @property
    def text(self) -> str:
        return self.content.decode()


class _Client:
    def __init__(self, app) -> None:
        self.app = app

    def get(self, path: str) -> _Response:
        query = b""
        if "?" in path:
            path, raw_query = path.split("?", 1)
            query = raw_query.encode()
        sent: list[dict] = []

        async def receive() -> dict:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: dict) -> None:
            sent.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query,
            "headers": [(b"host", b"testserver")],
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
        }
        asyncio.run(self.app(scope, receive, send))
        start = next(item for item in sent if item["type"] == "http.response.start")
        headers = {key.decode(): value.decode() for key, value in start.get("headers", [])}
        body = b"".join(item.get("body", b"") for item in sent if item["type"] == "http.response.body")
        return _Response(start["status"], headers, body)


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
    from fastapi import FastAPI
    from api.routes.storefront import router

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

    app = FastAPI()
    app.include_router(router)
    return _Client(app)


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


def test_product_html_is_allowlisted_and_not_reflective(client):
    import backend.commerce.catalog as cat_mod
    cat_mod.product_catalog.register(CatalogEntry(
        product_id="marked-roller", brand_id="beauty", title="Marked Roller",
        retail_price=12.00, status=STATUS_LIVE,
        description_html="<p>Cooling facial massage.</p><script>zz-storefront-xss</script><img src=x onerror=alert(1)>",
        bullets=["Natural jade"],
    ))
    resp = client.get("/s/beauty/marked-roller")
    assert resp.status_code == 200
    assert "<p>Cooling facial massage.</p>" in resp.text
    assert "<script" not in resp.text.lower()
    assert "onerror" not in resp.text.lower()
    assert "zz-storefront-xss" not in resp.text


def test_brand_id_is_escaped_in_markup(client):
    import backend.commerce.brands as brands_mod
    import backend.commerce.catalog as cat_mod
    brands_mod.brand_registry.upsert(Brand(
        brand_id='q"><svg', name="Quoted Brand", category="quoted", tagline="safe",
    ))
    cat_mod.product_catalog.register(CatalogEntry(
        product_id="safe-item", brand_id='q"><svg', title="Safe Item",
        retail_price=5.00, status=STATUS_LIVE,
    ))
    resp = client.get('/s/q"><svg')
    assert resp.status_code == 200
    assert "<svg" not in resp.text.lower()
    assert "Quoted Brand" in resp.text

    product = client.get('/s/q"><svg/safe-item')
    assert product.status_code == 200
    assert "<svg" not in product.text.lower()
    assert "href='/s/q&quot;&gt;&lt;svg'" in product.text


def test_checkout_redirect_allows_only_the_provider_contract(client, monkeypatch):
    import backend.commerce.checkout as checkout

    def _fake(url, dry_run, session_id="cs_test_synthetic"):
        def _call(brand_id, product_id, qty=1, utm=None):
            assert utm == {"utm_source": "tiktok"}
            return {"status": "ok", "session_id": session_id, "url": url, "dry_run": dry_run}
        return _call

    allowed = "https://checkout.stripe.com/c/pay/cs_test_synthetic"
    monkeypatch.setattr(checkout, "create_checkout_session", _fake(allowed, False))
    live = client.get("/s/beauty/jade-roller/checkout?utm_source=tiktok&other=x")
    assert live.status_code == 303
    assert live.headers["location"] == allowed

    local = "http://localhost:8000/s/beauty/jade-roller?purchased=1"
    monkeypatch.setattr(checkout, "create_checkout_session", _fake(local, True))
    dry = client.get("/s/beauty/jade-roller/checkout?utm_source=tiktok")
    assert dry.status_code == 303
    assert dry.headers["location"] == local

    rejected = (
        "https://evil.example/pay",
        "https://checkout.stripe.com.evil.example/c/pay/cs_test_synthetic",
        "https://checkout.stripe.com/c/pay/cs_test_synthetic/next",
        "https://checkout.stripe.com/c/pay/cs_test_synthetic?next=https://evil.example",
        "https://Checkout.stripe.com/c/pay/cs_test_synthetic",
        "https://user@checkout.stripe.com/c/pay/cs_test_synthetic",
        "http://checkout.stripe.com/c/pay/cs_test_synthetic",
        "javascript:alert(1)",
        "https://localhost:8000/s/beauty/jade-roller?purchased=1",
    )
    for url in rejected:
        dry_run = url.startswith("https://localhost:8000/")
        monkeypatch.setattr(checkout, "create_checkout_session", _fake(url, dry_run, session_id="not-a-stripe-session"))
        resp = client.get("/s/beauty/jade-roller/checkout?utm_source=tiktok")
        assert resp.status_code == 409
        assert "location" not in {key.lower() for key in resp.headers}
        assert url not in resp.text
        assert "checkout.stripe.com" not in resp.text
        assert "evil.example" not in resp.text
