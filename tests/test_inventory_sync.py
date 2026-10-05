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

    def test_supplier_quote_fetch_is_offline_and_non_mutating_by_default(self, commerce, monkeypatch):
        import backend.commerce.inventory_sync as inv_mod
        import backend.validation.suppliers as suppliers

        monkeypatch.setenv("INVENTORY_SYNC_LIVE", "true")
        monkeypatch.delenv("INVENTORY_SYNC_QUOTES_LIVE", raising=False)
        calls = []
        monkeypatch.setattr(
            suppliers,
            "quote_all",
            lambda name: calls.append(name) or [_fake_quote(landed_cost=8.0)],
        )
        _, catalog, brand = commerce

        result = inv_mod.reconcile_brand(brand)

        assert result["actions"] == [{
            "action": "skip_unavailable",
            "product_id": "jade-roller",
            "reason": "supplier_quote_fetch_disabled",
            "applied": False,
        }]
        assert calls == []
        assert catalog.get("jade-roller").retail_price == 19.99
        assert catalog.get("jade-roller").status == STATUS_LIVE

    def test_supplier_quote_fetch_requires_explicit_opt_in(self, commerce, monkeypatch):
        import backend.commerce.inventory_sync as inv_mod
        import backend.validation.suppliers as suppliers

        monkeypatch.setenv("INVENTORY_SYNC_QUOTES_LIVE", "true")
        calls = []
        monkeypatch.setattr(
            suppliers,
            "quote_all",
            lambda name: calls.append(name) or [_fake_quote(landed_cost=8.0)],
        )
        _, catalog, brand = commerce

        result = inv_mod.reconcile_brand(brand)

        assert calls == ["Jade Roller"]
        assert result["actions"][0]["action"] == "reprice"
        assert result["live"] is False
        assert catalog.get("jade-roller").retail_price == 19.99

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
        monkeypatch.setenv("INVENTORY_SYNC_QUOTES_LIVE", "true")

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
        monkeypatch.setenv("INVENTORY_SYNC_QUOTES_LIVE", "true")
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
        monkeypatch.setenv("INVENTORY_SYNC_QUOTES_LIVE", "true")

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

    def test_mapping_offer_provenance_preserved(self, commerce):
        import backend.commerce.inventory_sync as inv_mod

        offer = {
            "supplier_id": "cjdropshipping",
            "product_id": "cj_sku_1",
            "landed_cost": 8.0,
            "inventory_units": 10,
            "quality": {
                "provenance": "manual",
                "source_ref": "inventory-feed:offer-1",
            },
        }
        _, catalog, brand = commerce
        result = inv_mod.reconcile_brand(brand, offers={"jade-roller": offer})

        assert result["actions"][0]["action"] == "reprice"
        assert result["actions"][0]["provenance"] == {
            "supplier": "cjdropshipping",
            "supplier_product_id": "cj_sku_1",
            "provenance": "manual",
            "source_ref": "inventory-feed:offer-1",
        }
        assert catalog.get("jade-roller").retail_price == 19.99

    def test_unmatched_generic_mapping_offer_is_not_used_for_product(self, commerce):
        import backend.commerce.inventory_sync as inv_mod

        _, catalog, brand = commerce
        catalog.update("jade-roller", supplier="")
        unrelated_offer = {
            "supplier_id": "spocket",
            "product_id": "totally-other",
            "product_name": "Another Product",
            "landed_cost": 8.0,
            "inventory_units": 10,
        }

        result = inv_mod.reconcile_brand(brand, offers={"": unrelated_offer})

        assert result["actions"] == [{
            "action": "pause_stockout",
            "product_id": "jade-roller",
            "reason": "no_supplier_quote",
        }]
        assert catalog.get("jade-roller").retail_price == 19.99

    def test_empty_identity_mapping_fallback_is_not_used_for_product(self, commerce):
        import backend.commerce.inventory_sync as inv_mod

        _, catalog, brand = commerce
        offer = {
            "supplier_id": "cjdropshipping",
            "product_id": "",
            "supplier_product_id": "",
            "landed_cost": 8.0,
            "inventory_units": 10,
        }

        result = inv_mod.reconcile_brand(brand, offers={"": offer})

        assert result["actions"] == [{
            "action": "pause_stockout",
            "product_id": "jade-roller",
            "reason": "no_supplier_quote",
            "provenance": {"supplier": "cjdropshipping"},
        }]
        assert catalog.get("jade-roller").retail_price == 19.99

    @pytest.mark.parametrize("mapping_key", ["jade-roller", "Jade Roller"])
    def test_keyed_mapping_filters_offers_for_other_products(self, commerce, mapping_key):
        import backend.commerce.inventory_sync as inv_mod

        _, catalog, brand = commerce
        catalog.update("jade-roller", supplier="")
        unrelated = {
            "supplier_id": "spocket",
            "product_id": "other-sku",
            "product_name": "Another Product",
            "landed_cost": 20.0,
            "inventory_units": 10,
        }
        matching = {
            "supplier_id": "cjdropshipping",
            "product_id": "cj_sku_1",
            "product_name": "Jade Roller",
            "landed_cost": 8.0,
            "inventory_units": 10,
        }

        list_result = inv_mod.reconcile_brand(brand, offers=[unrelated, matching])
        mapping_result = inv_mod.reconcile_brand(
            brand, offers={mapping_key: [unrelated, matching]}
        )

        assert list_result["actions"][0]["action"] == "reprice"
        assert mapping_result["actions"] == list_result["actions"]

    def test_keyed_mapping_allows_offer_without_repeated_product_identity(self, commerce):
        import backend.commerce.inventory_sync as inv_mod

        _, catalog, brand = commerce
        offer = {
            "supplier_id": "cjdropshipping",
            "landed_cost": 8.0,
            "inventory_units": 10,
        }

        result = inv_mod.reconcile_brand(brand, offers={"jade-roller": offer})

        assert result["actions"][0]["action"] == "reprice"
        assert catalog.get("jade-roller").retail_price == 19.99

    def test_user_mapping_offer_is_reconciled_with_provenance(self, commerce):
        from collections import UserDict
        import backend.commerce.inventory_sync as inv_mod

        offer = UserDict({
            "supplier_id": "cjdropshipping",
            "product_id": "cj_sku_1",
            "landed_cost": 8.0,
            "inventory_units": 10,
            "quality": UserDict({
                "provenance": "manual",
                "source_ref": "inventory-feed:offer-2",
            }),
        })
        _, catalog, brand = commerce

        result = inv_mod.reconcile_brand(brand, offers={"jade-roller": offer})

        assert result["actions"][0]["action"] == "reprice"
        assert result["actions"][0]["provenance"] == {
            "supplier": "cjdropshipping",
            "supplier_product_id": "cj_sku_1",
            "provenance": "manual",
            "source_ref": "inventory-feed:offer-2",
        }
        assert catalog.get("jade-roller").retail_price == 19.99

    def test_mapping_offer_identity_uses_nonempty_supplier_aliases(self, commerce):
        import backend.commerce.inventory_sync as inv_mod

        _, catalog, brand = commerce
        catalog.update("jade-roller", supplier_product_id="cj_sku_1")
        offer = {
            "supplier": "",
            "supplier_id": "cjdropshipping",
            "product_id": "",
            "supplier_product_id": "cj_sku_1",
            "landed_cost": 8.0,
            "inventory_units": 10,
        }

        result = inv_mod.reconcile_brand(brand, offers=[offer])

        assert result["actions"][0]["action"] == "reprice"
        assert result["actions"][0]["provenance"]["supplier"] == "cjdropshipping"
        assert result["actions"][0]["provenance"]["supplier_product_id"] == "cj_sku_1"

    def test_invalid_attribute_quote_cost_is_skipped_without_live_mutation(self, commerce, monkeypatch):
        import backend.commerce.inventory_sync as inv_mod
        from backend.validation.suppliers import SupplierQuote

        monkeypatch.setenv("INVENTORY_SYNC_LIVE", "true")
        quote = SupplierQuote(
            supplier="cjdropshipping",
            product_id="cj_sku_1",
            product_name="Jade Roller",
            cost="not-a-number",  # type: ignore[arg-type]
            shipping=2.4,
            fulfillment_days=7,
            reliability=0.9,
        )
        _, catalog, brand = commerce

        result = inv_mod.reconcile_brand(brand, offers=[quote])

        assert result["actions"] == [{
            "action": "skip_invalid",
            "product_id": "jade-roller",
            "reason": "invalid_landed_cost",
            "provenance": {
                "supplier": "cjdropshipping",
                "supplier_product_id": "cj_sku_1",
            },
            "applied": False,
        }]
        assert catalog.get("jade-roller").retail_price == 19.99
        assert catalog.get("jade-roller").status == STATUS_LIVE

    def test_invalid_landed_cost_is_skipped_without_aborting_reconciliation(self, commerce, monkeypatch):
        import backend.commerce.inventory_sync as inv_mod

        monkeypatch.setenv("INVENTORY_SYNC_LIVE", "true")
        offer = {
            "supplier_id": "cjdropshipping",
            "product_id": "cj_sku_1",
            "landed_cost": "not-a-number",
            "inventory_units": 10,
        }
        _, catalog, brand = commerce
        catalog.register(CatalogEntry(
            product_id="other-product", brand_id="beauty", title="Other Product",
            retail_price=10.0, supplier="cjdropshipping", landed_cost=2.0,
            status=STATUS_LIVE,
        ))
        valid_offer = {
            "supplier_id": "cjdropshipping",
            "product_id": "other-sku",
            "landed_cost": 4.0,
            "inventory_units": 10,
        }

        result = inv_mod.reconcile_brand(brand, offers={
            "jade-roller": offer,
            "other-product": valid_offer,
        })

        assert result["actions"][0] == {
            "action": "skip_invalid",
            "product_id": "jade-roller",
            "reason": "invalid_landed_cost",
            "provenance": {
                "supplier": "cjdropshipping",
                "supplier_product_id": "cj_sku_1",
            },
            "applied": False,
        }
        assert result["actions"][1]["action"] == "reprice"
        assert result["actions"][1]["product_id"] == "other-product"
        assert catalog.get("jade-roller").retail_price == 19.99
        assert catalog.get("other-product").retail_price != 10.0

    def test_invalid_inventory_quantity_is_skipped_without_live_mutation(self, commerce, monkeypatch):
        import backend.commerce.inventory_sync as inv_mod

        monkeypatch.setenv("INVENTORY_SYNC_LIVE", "true")
        offer = {
            "supplier_id": "cjdropshipping",
            "product_id": "cj_sku_1",
            "landed_cost": 8.0,
            "inventory_units": "many",
        }
        _, catalog, brand = commerce

        result = inv_mod.reconcile_brand(brand, offers={"jade-roller": offer})

        assert result["actions"] == [{
            "action": "skip_invalid",
            "product_id": "jade-roller",
            "reason": "invalid_inventory_units",
            "provenance": {
                "supplier": "cjdropshipping",
                "supplier_product_id": "cj_sku_1",
            },
            "applied": False,
        }]
        assert catalog.get("jade-roller").retail_price == 19.99
        assert catalog.get("jade-roller").status == STATUS_LIVE

    def test_naive_observation_timestamp_is_fresh_without_live_mutation(self, commerce):
        from datetime import datetime
        import backend.commerce.inventory_sync as inv_mod

        offer = {
            "supplier_id": "cjdropshipping",
            "product_id": "cj_sku_1",
            "landed_cost": 8.0,
            "inventory_units": 10,
            "quality": {
                "provenance": "manual",
                "observed_at": datetime.now().isoformat(),
            },
        }
        _, catalog, brand = commerce

        result = inv_mod.reconcile_brand(brand, offers={"jade-roller": offer})

        assert result["actions"][0]["action"] == "reprice"
        assert result["actions"][0]["provenance"] == {
            "supplier": "cjdropshipping",
            "supplier_product_id": "cj_sku_1",
            "provenance": "manual",
        }
        assert result["live"] is False
        assert catalog.get("jade-roller").retail_price == 19.99
        assert catalog.get("jade-roller").status == STATUS_LIVE

    def test_naive_datetime_observation_is_fresh_without_live_mutation(self, commerce):
        from datetime import datetime
        import backend.commerce.inventory_sync as inv_mod

        offer = {
            "supplier_id": "cjdropshipping",
            "product_id": "cj_sku_1",
            "landed_cost": 8.0,
            "inventory_units": 10,
            "quality": {
                "provenance": "manual",
                "observed_at": datetime.now(),
            },
        }
        _, catalog, brand = commerce

        result = inv_mod.reconcile_brand(brand, offers={"jade-roller": offer})

        assert result["actions"][0]["action"] == "reprice"
        assert result["live"] is False
        assert catalog.get("jade-roller").retail_price == 19.99
        assert catalog.get("jade-roller").status == STATUS_LIVE

    def test_naive_data_quality_object_is_fresh_without_live_mutation(self, commerce):
        from datetime import datetime
        from evaluation.contracts import DataQuality, SupplierOffer
        import backend.commerce.inventory_sync as inv_mod

        offer = SupplierOffer(
            supplier_id="cjdropshipping",
            product_id="jade-roller",
            unit_cost=5.0,
            shipping_cost=3.0,
            inventory_units=10,
            quality=DataQuality(observed_at=datetime.now()),
        )
        _, catalog, brand = commerce

        result = inv_mod.reconcile_brand(brand, offers=[offer])

        assert result["actions"][0]["action"] == "reprice"
        assert result["live"] is False
        assert catalog.get("jade-roller").retail_price == 19.99
        assert catalog.get("jade-roller").status == STATUS_LIVE

    def test_invalid_observation_timestamp_is_skipped_without_live_mutation(self, commerce, monkeypatch):
        import backend.commerce.inventory_sync as inv_mod

        monkeypatch.setenv("INVENTORY_SYNC_LIVE", "true")
        offer = {
            "supplier_id": "cjdropshipping",
            "product_id": "cj_sku_1",
            "landed_cost": 8.0,
            "inventory_units": 10,
            "quality": {
                "provenance": "manual",
                "observed_at": 1234567890,
            },
        }
        _, catalog, brand = commerce

        result = inv_mod.reconcile_brand(brand, offers={"jade-roller": offer})

        assert result["actions"] == [{
            "action": "skip_stale",
            "product_id": "jade-roller",
            "reason": "stale_observation",
            "provenance": {
                "supplier": "cjdropshipping",
                "supplier_product_id": "cj_sku_1",
                "provenance": "manual",
            },
            "applied": False,
        }]
        assert catalog.get("jade-roller").retail_price == 19.99
        assert catalog.get("jade-roller").status == STATUS_LIVE

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

    def test_conflicting_inventory_order_is_conservative_and_deterministic(self, commerce):
        import backend.commerce.inventory_sync as inv_mod
        from evaluation.contracts import SupplierOffer

        available = SupplierOffer(
            supplier_id="cjdropshipping",
            product_id="jade-roller",
            unit_cost=5.0,
            shipping_cost=3.0,
            inventory_units=10,
        )
        stockout = SupplierOffer(
            supplier_id="cjdropshipping",
            product_id="jade-roller",
            unit_cost=5.0,
            shipping_cost=3.0,
            inventory_units=0,
        )
        _, catalog, brand = commerce

        forward = inv_mod.reconcile_brand(brand, offers=[available, stockout])
        reverse = inv_mod.reconcile_brand(brand, offers=[stockout, available])

        assert forward["actions"] == reverse["actions"]
        assert forward["actions"] == [{
            "action": "pause_stockout",
            "product_id": "jade-roller",
            "reason": "zero_inventory_units",
            "provenance": {
                "supplier": "cjdropshipping",
                "supplier_product_id": "jade-roller",
                "provenance": "unknown",
            },
        }]
        assert catalog.get("jade-roller").status == STATUS_LIVE

    def test_conflicting_positive_quantities_fail_closed_in_both_orders(self, commerce):
        import backend.commerce.inventory_sync as inv_mod
        from evaluation.contracts import SupplierOffer

        offers = [
            SupplierOffer(
                supplier_id="cjdropshipping",
                product_id="jade-roller",
                unit_cost=5.0,
                shipping_cost=3.0,
                inventory_units=10,
            ),
            SupplierOffer(
                supplier_id="cjdropshipping",
                product_id="jade-roller",
                unit_cost=5.0,
                shipping_cost=3.0,
                inventory_units=20,
            ),
        ]
        _, _, brand = commerce

        forward = inv_mod.reconcile_brand(brand, offers=offers)
        reverse = inv_mod.reconcile_brand(brand, offers=list(reversed(offers)))

        assert forward["actions"] == reverse["actions"]
        assert forward["actions"][0]["action"] == "pause_stockout"
        assert forward["actions"][0]["reason"] == "no_supplier_quote"

    def test_duplicate_observations_use_stable_provenance_order(self, commerce):
        from evaluation.contracts import DataQuality, SupplierOffer
        import backend.commerce.inventory_sync as inv_mod

        first = SupplierOffer(
            supplier_id="cjdropshipping",
            product_id="jade-roller",
            unit_cost=5.0,
            shipping_cost=3.0,
            quality=DataQuality(source_ref="feed-b"),
        )
        second = SupplierOffer(
            supplier_id="cjdropshipping",
            product_id="jade-roller",
            unit_cost=5.0,
            shipping_cost=3.0,
            quality=DataQuality(source_ref="feed-a"),
        )
        _, _, brand = commerce

        forward = inv_mod.reconcile_brand(brand, offers=[first, second])
        reverse = inv_mod.reconcile_brand(brand, offers=[second, first])

        assert forward["actions"] == reverse["actions"]
        assert forward["actions"][0]["provenance"]["source_ref"] == "feed-a"

    def test_missing_and_explicit_zero_inventory_remain_distinct(self, commerce):
        from evaluation.contracts import SupplierOffer
        import backend.commerce.inventory_sync as inv_mod

        missing = SupplierOffer(
            supplier_id="cjdropshipping",
            product_id="jade-roller",
            unit_cost=3.6,
            shipping_cost=2.4,
            inventory_units=None,
        )
        explicit_zero = SupplierOffer(
            supplier_id="cjdropshipping",
            product_id="jade-roller",
            unit_cost=3.6,
            shipping_cost=2.4,
            inventory_units=0,
        )
        _, _, brand = commerce

        missing_result = inv_mod.reconcile_brand(brand, offers=[missing])
        zero_result = inv_mod.reconcile_brand(brand, offers=[explicit_zero])
        mixed_result = inv_mod.reconcile_brand(brand, offers=[missing, explicit_zero])

        assert missing_result["actions"] == []
        assert zero_result["actions"][0]["reason"] == "zero_inventory_units"
        assert mixed_result["actions"][0]["reason"] == "zero_inventory_units"

    def test_fresh_observation_wins_over_stale_reordering(self, commerce):
        from datetime import datetime, timedelta, timezone
        from evaluation.contracts import DataQuality, SupplierOffer
        import backend.commerce.inventory_sync as inv_mod

        stale = SupplierOffer(
            supplier_id="cjdropshipping",
            product_id="jade-roller",
            unit_cost=5.0,
            shipping_cost=3.0,
            inventory_units=0,
            quality=DataQuality(
                observed_at=datetime.now(timezone.utc) - timedelta(days=5),
                source_ref="stale-feed",
            ),
        )
        fresh = SupplierOffer(
            supplier_id="cjdropshipping",
            product_id="jade-roller",
            unit_cost=5.0,
            shipping_cost=3.0,
            inventory_units=10,
            quality=DataQuality(source_ref="fresh-feed"),
        )
        _, _, brand = commerce

        forward = inv_mod.reconcile_brand(brand, offers=[stale, fresh])
        reverse = inv_mod.reconcile_brand(brand, offers=[fresh, stale])

        assert forward["actions"] == reverse["actions"]
        assert forward["actions"][0]["action"] == "reprice"
        assert forward["actions"][0]["provenance"]["source_ref"] == "fresh-feed"

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

    @pytest.mark.parametrize(
        "offers_by_brand",
        [{}, {"other-brand": []}, {"beauty": None}],
    )
    def test_offline_batch_missing_brand_observations_do_not_query_suppliers(
        self, commerce, monkeypatch, offers_by_brand
    ):
        import backend.commerce.inventory_sync as inv_mod
        import backend.validation.suppliers as suppliers

        monkeypatch.setenv("INVENTORY_SYNC_QUOTES_LIVE", "true")
        monkeypatch.setenv("INVENTORY_SYNC_LIVE", "true")
        calls = []
        monkeypatch.setattr(suppliers, "quote_all", lambda name: calls.append(name) or [])

        result = inv_mod.reconcile_all_brands(offers_by_brand=offers_by_brand)

        assert result["products_checked"] == 1
        assert result["brands_checked"] == 1
        assert calls == []
        _, catalog, _ = commerce
        assert catalog.get("jade-roller").status == STATUS_LIVE
        assert catalog.get("jade-roller").retail_price == 19.99
