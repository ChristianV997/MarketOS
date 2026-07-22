"""Tests for backend.validation.suppliers — place_order/order_status (Phase D)."""
import pytest

from backend.validation.suppliers import (
    CJDropshippingClient,
    PrintfulClient,
    SpocketClient,
    ZendropClient,
    get_client,
)


@pytest.fixture(autouse=True)
def _dry_env(monkeypatch):
    monkeypatch.delenv("SUPPLIER_ORDERS_DRY_RUN", raising=False)
    monkeypatch.delenv("CJ_API_KEY", raising=False)
    yield


def _order(order_id="o1"):
    return {
        "order_id": order_id, "supplier_product_id": "sp_1", "qty": 1,
        "shipping": {"line1": "1 Main St", "city": "Austin", "state": "TX",
                    "postal_code": "78701", "country": "US"},
    }


class TestDryRunOrdering:
    def test_place_order_dry_by_default(self):
        client = CJDropshippingClient()
        result = client.place_order(_order())
        assert result["status"] == "ok"
        assert result["dry_run"] is True
        assert result["supplier_order_id"].startswith("dry_so_")

    def test_place_order_idempotent_for_same_order_id(self):
        client = CJDropshippingClient()
        a = client.place_order(_order("o1"))
        b = client.place_order(_order("o1"))
        assert a["supplier_order_id"] == b["supplier_order_id"]

    def test_different_orders_get_different_ids(self):
        client = CJDropshippingClient()
        a = client.place_order(_order("o1"))
        b = client.place_order(_order("o2"))
        assert a["supplier_order_id"] != b["supplier_order_id"]

    def test_order_status_dry_deterministic(self):
        client = CJDropshippingClient()
        placed = client.place_order(_order("o1"))
        s1 = client.order_status(placed["supplier_order_id"])
        s2 = client.order_status(placed["supplier_order_id"])
        assert s1 == s2
        assert s1["status"] in ("shipped", "placed")

    def test_all_four_suppliers_support_dry_ordering(self):
        for client in (CJDropshippingClient(), ZendropClient(),
                      SpocketClient(), PrintfulClient()):
            result = client.place_order(_order(f"o_{client.name}"))
            assert result["status"] == "ok"
            assert result["dry_run"] is True


class TestGetClient:
    def test_lookup_by_name(self):
        assert get_client("cj_dropshipping").__class__ is CJDropshippingClient
        assert get_client("zendrop").__class__ is ZendropClient
        assert get_client("spocket").__class__ is SpocketClient
        assert get_client("printful").__class__ is PrintfulClient

    def test_unknown_name_returns_none(self):
        assert get_client("nonexistent") is None


class TestQuotingVsOrderingIndependence:
    def test_orders_stay_dry_even_with_live_quoting(self, monkeypatch):
        # SUPPLIERS_DRY_RUN=false (live quoting attempted) must NOT imply
        # live ordering — SUPPLIER_ORDERS_DRY_RUN defaults true independently.
        monkeypatch.setenv("SUPPLIERS_DRY_RUN", "false")
        client = CJDropshippingClient()
        result = client.place_order(_order())
        assert result["dry_run"] is True

    def test_live_ordering_without_api_key_stays_dry(self, monkeypatch):
        monkeypatch.setenv("SUPPLIER_ORDERS_DRY_RUN", "false")
        # No CJ_API_KEY configured -> is_configured() is False -> stays dry
        client = CJDropshippingClient()
        result = client.place_order(_order())
        assert result["dry_run"] is True


class TestLiveOrderPlacementNotImplementedForUnfinishedSuppliers:
    def test_zendrop_live_place_order_raises_not_implemented(self, monkeypatch):
        monkeypatch.setenv("SUPPLIER_ORDERS_DRY_RUN", "false")
        monkeypatch.setenv("ZENDROP_API_KEY", "fake")
        client = ZendropClient()
        with pytest.raises(NotImplementedError):
            client._live_place_order(_order())
