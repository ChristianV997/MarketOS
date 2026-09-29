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

    def test_explicit_zero_inventory_units_triggers_pause_stockout(self, commerce, monkeypatch):
        import backend.commerce.inventory_sync as inv_mod
        from evaluation.contracts import SupplierOffer

        # Supplier offer with explicit 0 inventory units must trigger stockout pause
        offer = SupplierOffer(
            supplier_id="cjdropshipping",
            product_id="cj_1",
            unit_cost=3.6,
            shipping_cost=2.4,
            inventory_units=0,
        )
        monkeypatch.setattr(inv_mod, "_requote", lambda entry, offers=None: offer)

        _, catalog, brand = commerce
        result = inv_mod.reconcile_brand(brand)
        assert len(result["actions"]) == 1
        action = result["actions"][0]
        assert action["action"] == "pause_stockout"
        assert action["reason"] == "zero_inventory_units"
        assert action["product_id"] == "jade-roller"

    def test_unknown_inventory_units_preserved_no_false_stockout(self, commerce, monkeypatch):
        import backend.commerce.inventory_sync as inv_mod
        from evaluation.contracts import SupplierOffer

        # Supplier offer with inventory_units=None (unknown) must NOT trigger stockout
        offer = SupplierOffer(
            supplier_id="cjdropshipping",
            product_id="cj_1",
            unit_cost=3.6,
            shipping_cost=2.4,
            inventory_units=None,
        )
        monkeypatch.setattr(inv_mod, "_requote", lambda entry, offers=None: offer)

        _, catalog, brand = commerce
        result = inv_mod.reconcile_brand(brand)
        assert result["actions"] == []  # No drift, not out of stock

    def test_stock_ok_false_triggers_pause_stockout(self, commerce, monkeypatch):
        import backend.commerce.inventory_sync as inv_mod
        from backend.validation.suppliers import SupplierQuote

        quote = SupplierQuote(
            supplier="cjdropshipping", product_id="cj_1", product_name="Jade Roller",
            cost=3.6, shipping=2.4, fulfillment_days=7, reliability=0.9,
        )
        quote.stock_ok = False
        monkeypatch.setattr(inv_mod, "_requote", lambda entry, offers=None: quote)

        _, catalog, brand = commerce
        result = inv_mod.reconcile_brand(brand)
        assert len(result["actions"]) == 1
        assert result["actions"][0]["action"] == "pause_stockout"
        assert result["actions"][0]["reason"] == "supplier_out_of_stock"

    def test_requote_prefers_supplier_product_id_match(self, commerce, monkeypatch):
        from backend.commerce.catalog import product_catalog
        from backend.validation.suppliers import SupplierQuote
        import backend.commerce.inventory_sync as inv_mod

        # Update entry with specific supplier_product_id
        product_catalog.update("jade-roller", supplier_product_id="cj_specific_sku")

        # Two quotes from same supplier, one matching the exact SKU
        wrong_sku = SupplierQuote(supplier="cjdropshipping", product_id="cj_wrong_sku",
                                  product_name="Jade Roller", cost=5.0, shipping=3.0,
                                  fulfillment_days=7, reliability=0.9)
        exact_sku = SupplierQuote(supplier="cjdropshipping", product_id="cj_specific_sku",
                                  product_name="Jade Roller", cost=3.6, shipping=2.4,
                                  fulfillment_days=7, reliability=0.9)

        monkeypatch.setattr(
            "backend.validation.suppliers.quote_all",
            lambda name: [wrong_sku, exact_sku],
        )
        _, catalog, brand = commerce
        entry = catalog.get("jade-roller")
        matched = inv_mod._requote(entry)
        assert matched is not None
        assert matched.product_id == "cj_specific_sku"
        # Landed cost 6.0 matches catalog landed cost -> no drift action
        result = inv_mod.reconcile_brand(brand)
        assert result["actions"] == []

    def test_stale_observation_skipped_no_action(self, commerce, monkeypatch):
        from datetime import datetime, timezone, timedelta
        import backend.commerce.inventory_sync as inv_mod
        from evaluation.contracts import DataQuality, SupplierOffer

        # Stale offer (observed 5 days ago > 48h max age)
        stale_quality = DataQuality(
            provenance="live",
            attribution="attributed",
            observed_at=datetime.now(timezone.utc) - timedelta(days=5),
            source_ref="supplier_feed:001",
        )
        stale_offer = SupplierOffer(
            supplier_id="cjdropshipping",
            product_id="cj_1",
            unit_cost=10.0,
            shipping_cost=5.0,
            quality=stale_quality,
        )
        monkeypatch.setattr(inv_mod, "_requote", lambda entry, offers=None: stale_offer)

        _, catalog, brand = commerce
        result = inv_mod.reconcile_brand(brand)
        assert len(result["actions"]) == 1
        action = result["actions"][0]
        assert action["action"] == "skip_stale"
        assert action["reason"] == "stale_observation"
        # Catalog must not have been mutated
        assert catalog.get("jade-roller").retail_price == 19.99

    def test_offline_offers_batch_reconciliation(self, commerce):
        import backend.commerce.inventory_sync as inv_mod
        from evaluation.contracts import SupplierOffer

        # Pass offline batch offers directly to reconcile_brand
        offers = [
            SupplierOffer(
                supplier_id="cjdropshipping",
                product_id="jade-roller",
                unit_cost=5.0,
                shipping_cost=3.0,  # landed 8.0 -> reprice drift
            )
        ]
        _, catalog, brand = commerce
        result = inv_mod.reconcile_brand(brand, offers=offers)
        assert result["checked"] == 1
        assert len(result["actions"]) == 1
        assert result["actions"][0]["action"] == "reprice"
        assert result["actions"][0]["new_landed_cost"] == 8.0

    def test_action_provenance_preserved(self, commerce, monkeypatch):
        import backend.commerce.inventory_sync as inv_mod
        from evaluation.contracts import DataQuality, SupplierOffer

        quality = DataQuality(
            provenance="live",
            attribution="attributed",
            source_ref="cjdropshipping:offer_999",
        )
        offer = SupplierOffer(
            supplier_id="cjdropshipping",
            product_id="cj_sku_1",
            unit_cost=5.0,
            shipping_cost=3.0,
            quality=quality,
        )
        monkeypatch.setattr(inv_mod, "_requote", lambda entry, offers=None: offer)

        _, catalog, brand = commerce
        result = inv_mod.reconcile_brand(brand)
        assert len(result["actions"]) == 1
        action = result["actions"][0]
        assert "provenance" in action
        prov = action["provenance"]
        assert prov["supplier"] == "cjdropshipping"
        assert prov["supplier_product_id"] == "cj_sku_1"
        assert prov["provenance"] == "live"
        assert prov["source_ref"] == "cjdropshipping:offer_999"

    def test_duplicate_observations_deduplicated_idempotently(self, commerce):
        import backend.commerce.inventory_sync as inv_mod
        from evaluation.contracts import SupplierOffer

        # Duplicate offers for same product
        offer1 = SupplierOffer(
            supplier_id="cjdropshipping",
            product_id="jade-roller",
            unit_cost=5.0,
            shipping_cost=3.0,
        )
        offer2 = SupplierOffer(
            supplier_id="cjdropshipping",
            product_id="jade-roller",
            unit_cost=5.0,
            shipping_cost=3.0,
        )
        _, catalog, brand = commerce
        result = inv_mod.reconcile_brand(brand, offers=[offer1, offer2])
        assert result["checked"] == 1
        # Action only generated once, no duplicate action emitted
        assert len(result["actions"]) == 1
        assert result["actions"][0]["action"] == "reprice"

    def test_reconcile_all_brands_with_offers_by_brand(self, commerce):
        import backend.commerce.inventory_sync as inv_mod
        from evaluation.contracts import SupplierOffer

        offers_by_brand = {
            "beauty": [
                SupplierOffer(
                    supplier_id="cjdropshipping",
                    product_id="jade-roller",
                    unit_cost=5.0,
                    shipping_cost=3.0,
                )
            ]
        }
        result = inv_mod.reconcile_all_brands(offers_by_brand=offers_by_brand)
        assert result["status"] == "ok"
        assert result["products_checked"] == 1
        assert result["actions_taken"] == 1
        assert result["per_brand"] == [{"brand_id": "beauty", "actions": 1}]

    def test_stale_dict_quality_handled(self, commerce, monkeypatch):
        from datetime import datetime, timezone, timedelta
        import backend.commerce.inventory_sync as inv_mod

        stale_time = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        quote_dict = {
            "supplier": "cjdropshipping",
            "product_id": "cj_1",
            "cost": 5.0,
            "shipping": 3.0,
            "quality": {
                "provenance": "live",
                "attribution": "attributed",
                "observed_at": stale_time,
                "source_ref": "feed_1",
            }
        }
        monkeypatch.setattr(inv_mod, "_requote", lambda entry, offers=None: quote_dict)

        _, catalog, brand = commerce
        result = inv_mod.reconcile_brand(brand)
        assert len(result["actions"]) == 1
        assert result["actions"][0]["action"] == "skip_stale"
        assert result["actions"][0]["reason"] == "stale_observation"


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
