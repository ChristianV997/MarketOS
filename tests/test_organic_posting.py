"""Tests for backend.organic — poster candidates/publishing + engagement ingestion."""
import pytest

from backend.commerce.brands import Brand
from backend.commerce.catalog import STATUS_LIVE, CatalogEntry


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch, tmp_path):
    import backend.core.persistence as pers
    monkeypatch.setattr(pers, "STATE_DIR", str(tmp_path))
    monkeypatch.delenv("POSTIZ_URL", raising=False)
    monkeypatch.delenv("ORGANIC_DRY_RUN", raising=False)
    yield


@pytest.fixture
def commerce(monkeypatch):
    from backend.commerce.brands import BrandRegistry
    from backend.commerce.catalog import ProductCatalog
    import backend.commerce.brands as brands_mod
    import backend.commerce.catalog as cat_mod

    registry = BrandRegistry()
    catalog = ProductCatalog()
    monkeypatch.setattr(brands_mod, "brand_registry", registry)
    monkeypatch.setattr(cat_mod, "product_catalog", catalog)

    # Isolate from playbook state left behind by other tests in the full
    # suite — candidates must come only from this fixture's catalog.
    import core.content.playbook as pb_mod
    monkeypatch.setattr(pb_mod.playbook_memory, "all", lambda: [])

    registry.upsert(Brand(brand_id="beauty", name="Beauty Co", category="beauty",
                          channel_preferences={"tiktok": 0.7, "instagram": 0.3}))
    catalog.register(CatalogEntry(
        product_id="jade-roller", brand_id="beauty", title="Jade Roller",
        retail_price=19.99, status=STATUS_LIVE,
        page_url="http://localhost:8000/s/beauty/jade-roller",
    ))
    return registry, catalog


class TestOrganicPosting:
    def test_posts_live_catalog_products(self, commerce):
        from backend.organic.poster import run_organic_posting

        result = run_organic_posting()
        assert result["status"] == "ok"
        assert result["posted"] >= 1
        post = result["posts"][0]
        assert post["product"] == "Jade Roller"
        assert post["brand_id"] == "beauty"
        assert post["dry_run"] is True
        assert set(post["platforms"]) == {"tiktok", "instagram"}

    def test_no_duplicate_posts_within_window(self, commerce):
        from backend.organic.poster import run_organic_posting

        first = run_organic_posting()
        assert first["posted"] >= 1
        second = run_organic_posting()
        assert second["posted"] == 0  # recently posted -> skipped

    def test_utm_threaded_into_post_text(self, commerce, monkeypatch):
        from backend.organic import poster as poster_mod

        captured = {}

        def fake_create_post(text, platforms=None, **kw):
            captured["text"] = text
            return {"status": "ok", "post_id": "dry_post_x_1", "dry_run": True}

        import backend.integrations.postiz_client as pc
        monkeypatch.setattr(pc, "create_post", fake_create_post)
        poster_mod.run_organic_posting()
        assert "utm_source=organic" in captured["text"]
        assert "utm_campaign=beauty" in captured["text"]


class TestEngagementIngestion:
    def test_ingest_populates_rollup_and_classifies(self, commerce):
        from backend.organic.poster import run_organic_posting
        from backend.organic.engagement import ingest_engagement, product_engagement

        run_organic_posting()
        result = ingest_engagement()
        assert result["status"] == "ok"
        assert result["posts_measured"] >= 1

        rollup = product_engagement("Jade Roller")
        assert rollup["posts"] == 1
        assert rollup["impressions"] >= 500
        assert 0.0 < rollup["mean_engagement_rate"] < 0.2

    def test_reingest_does_not_double_count(self, commerce):
        from backend.organic.poster import run_organic_posting
        from backend.organic.engagement import ingest_engagement, product_engagement

        run_organic_posting()
        ingest_engagement()
        ingest_engagement()  # second pass re-measures, must not double count
        rollup = product_engagement("Jade Roller")
        assert rollup["posts"] == 1

    def test_unknown_product_returns_zeros(self):
        from backend.organic.engagement import product_engagement
        rollup = product_engagement("nope")
        assert rollup["posts"] == 0
        assert rollup["mean_engagement_rate"] == 0.0

    def test_skipped_when_no_posts(self):
        from backend.organic.engagement import ingest_engagement
        assert ingest_engagement()["status"] == "skipped"
