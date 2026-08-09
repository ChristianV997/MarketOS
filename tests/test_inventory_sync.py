"""Tests for backend.commerce.inventory_sync — reprice/stockout reconciliation."""
import pytest

from backend.commerce.brands import Brand
from backend.commerce.catalog import STATUS_LIVE, CatalogEntry


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch, tmp_path):
    import backend.core.persistence as pers
    monkeypatch.setattr(pers, "STATE_DIR", str(tmp_path))
    monkeypatch.delenv("INVENTORY_SYNC_LIVE", raising=False)
    yield


@pytest.fixture
def commerce(monkeypatch):
    from backend.commerce.brands import BrandRegistry
    from backend.commerce.catalog import ProductCatalog
    import backend.commerce.brands as brands_mod
    import backend.commerce.catalog as cat_mod
    import backend.commerce.storefront as sf_mod
    import backend.commerce.inventory_sync as inv_mod

    registry = BrandRegistry()
    catalog = ProductCatalog()
    monkeypatch.setattr(brands_mod, "brand_registry", registry)
    monkeypatch.setattr(cat_mod, "product_catalog", catalog)
    monkeypatch.setattr(sf_mod, "product_catalog", catalog)

    brand = Brand(brand_id="beauty", name="Beauty Co", category="beauty")
    registry.upsert(brand)
    catalog.register(CatalogEntry(
        product_id="jade-roller", brand_id="beauty", title="Jade Roller",
        retail_price=19.99, supplier="cjdropshipping", landed_cost=6.0,
        status=STATUS_LIVE,
    ))
    return registry, catalog, brand


def _fake_quote(supplier="cjdropshipping", landed_cost=6.0):
    from backend.validation.suppliers import SupplierQuote
    cost = landed_cost * 0.6
    shipping = landed_cost - cost
    return SupplierQuote(
        supplier=supplier, product_id="cj_1", product_name="Jade Roller",
        cost=round(cost, 2), shipping=round(shipping, 2),
        fulfillment_days=7, reliability=0.9,
    )


class TestReconcileBrand:
    def test_no_drift_no_action(self, commerce, monkeypatch):
        import backend.commerce.inventory_sync as inv_mod
        monkeypatch.setattr(inv_mod, "_requote", lambda entry: _fake_quote(landed_cost=6.0))

        _, catalog, brand = commerce
        result = inv_mod.reconcile_brand(brand)
        assert result["checked"] == 1
        assert result["actions"] == []

    def test_significant_drift_triggers_reprice_shadow_only(self, commerce, monkeypatch):
        import backend.commerce.inventory_sync as inv_mod
        # 6.0 -> 8.0 is a 33% jump, well above the 5% threshold
        monkeypatch.setattr(inv_mod, "_requote", lambda entry: _fake_quote(landed_cost=8.0))

        _, catalog, brand = commerce
        result = inv_mod.reconcile_brand(brand)
        assert result["live"] is False
        assert len(result["actions"]) == 1
        action = result["actions"][0]
        assert action["action"] == "reprice"
        assert action["old_price"] == 19.99
        assert action["new_landed_cost"] == 8.0
        assert action["drift_pct"] > 5.0

        # Shadow mode: catalog price must be unchanged
        assert catalog.get("jade-roller").retail_price == 19.99

    def test_small_drift_no_action(self, commerce, monkeypatch):
        import backend.commerce.inventory_sync as inv_mod
        # 6.0 -> 6.10 is ~1.7%, below the 5% threshold
        monkeypatch.setattr(inv_mod, "_requote", lambda entry: _fake_quote(landed_cost=6.10))

        _, catalog, brand = commerce
        result = inv_mod.reconcile_brand(brand)
        assert result["actions"] == []

    def test_no_quote_triggers_pause_stockout(self, commerce, monkeypatch):
        import backend.commerce.inventory_sync as inv_mod
        monkeypatch.setattr(inv_mod, "_requote", lambda entry: None)

        _, catalog, brand = commerce
        result = inv_mod.reconcile_brand(brand)
        assert result["actions"][0]["action"] == "pause_stockout"
        # Shadow mode: catalog untouched
        assert catalog.get("jade-roller").status == STATUS_LIVE

    def test_live_flag_applies_reprice(self, commerce, monkeypatch):
        monkeypatch.setenv("INVENTORY_SYNC_LIVE", "true")
        import backend.commerce.inventory_sync as inv_mod
        monkeypatch.setattr(inv_mod, "_requote", lambda entry: _fake_quote(landed_cost=8.0))

        _, catalog, brand = commerce
        result = inv_mod.reconcile_brand(brand)
        assert result["live"] is True
        updated = catalog.get("jade-roller")
        assert updated.retail_price != 19.99

    def test_live_flag_applies_pause(self, commerce, monkeypatch):
        monkeypatch.setenv("INVENTORY_SYNC_LIVE", "true")
        import backend.commerce.inventory_sync as inv_mod
        monkeypatch.setattr(inv_mod, "_requote", lambda entry: None)

        _, catalog, brand = commerce
        inv_mod.reconcile_brand(brand)
        updated = catalog.get("jade-roller")
        assert updated.stock_ok is False

    def test_requote_matches_bound_supplier_only(self, commerce, monkeypatch):
        from backend.validation.suppliers import SupplierQuote
        import backend.commerce.inventory_sync as inv_mod

        # Two quotes come back, only one matches the bound supplier
        other = SupplierQuote(supplier="spocket", product_id="sp_1",
                              product_name="Jade Roller", cost=3.0, shipping=1.0,
                              fulfillment_days=5, reliability=0.8)
        bound = _fake_quote(supplier="cjdropshipping", landed_cost=6.0)
        monkeypatch.setattr(
            "backend.validation.suppliers.quote_all",
            lambda name: [other, bound],
        )
        _, catalog, brand = commerce
        result = inv_mod.reconcile_brand(brand)
        assert result["actions"] == []  # matched cj quote, no drift

    def test_unbound_supplier_falls_back_to_first_quote(self, commerce, monkeypatch):
        from backend.commerce.catalog import product_catalog
        product_catalog.update("jade-roller", supplier="")
        import backend.commerce.inventory_sync as inv_mod
        monkeypatch.setattr(
            "backend.validation.suppliers.quote_all",
            lambda name: [_fake_quote(landed_cost=6.0)],
        )
        _, catalog, brand = commerce
        result = inv_mod.reconcile_brand(brand)
        assert result["actions"] == []  # matched the only quote


class TestReconcileAllBrands:
    def test_rollup_across_brands(self, commerce, monkeypatch):
        import backend.commerce.inventory_sync as inv_mod
        monkeypatch.setattr(inv_mod, "_requote", lambda entry: None)  # everything stockouts

        result = inv_mod.reconcile_all_brands()
        assert result["status"] == "ok"
        assert result["products_checked"] == 1
        assert result["actions_taken"] == 1
        assert result["per_brand"] == [{"brand_id": "beauty", "actions": 1}]

    def test_inactive_brand_skipped(self, commerce):
        import backend.commerce.inventory_sync as inv_mod
        registry, _, brand = commerce
        brand.active = False
        registry.upsert(brand)
        result = inv_mod.reconcile_all_brands()
        assert result["status"] == "skipped"
        assert result["products_checked"] == 0
