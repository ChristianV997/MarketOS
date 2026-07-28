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
    monkeypatch.delenv("CJ_EMAIL", raising=False)
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


class TestCJLiveOrderStatusMapping:
    """Tier 1 fix: an unrecognized/cancelled CJ status must never be
    silently reported as a healthy in-progress order."""

    def _status_response(self, order_status: str, monkeypatch):
        monkeypatch.setenv("CJ_API_KEY", "fake")
        monkeypatch.setenv("CJ_EMAIL", "ops@example.com")
        import backend.validation.suppliers as sup_mod
        monkeypatch.setattr(sup_mod, "_cj_token_manager", sup_mod._CJTokenManager())
        monkeypatch.setattr(sup_mod._cj_token_manager, "access_token", lambda: "fake_token")

        class _FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"data": {"orderStatus": order_status}}

        monkeypatch.setattr("requests.get", lambda *a, **kw: _FakeResponse())
        return CJDropshippingClient()._live_order_status("cj_so_1")

    def test_cancelled_maps_to_failed(self, monkeypatch):
        result = self._status_response("CANCELLED", monkeypatch)
        assert result["status"] == "failed"

    def test_exception_status_maps_to_failed(self, monkeypatch):
        result = self._status_response("EXCEPTION", monkeypatch)
        assert result["status"] == "failed"

    def test_unrecognized_status_maps_to_unknown_not_placed(self, monkeypatch):
        result = self._status_response("SOME_NEW_CJ_STATUS", monkeypatch)
        assert result["status"] == "unknown"

    def test_known_in_progress_statuses_still_map_to_placed(self, monkeypatch):
        assert self._status_response("CREATED", monkeypatch)["status"] == "placed"
        assert self._status_response("IN_PRODUCTION", monkeypatch)["status"] == "placed"


class TestCJIsConfigured:
    """Tier 5 fix: CJ's real auth exchanges (email, API key) for a token —
    api_key alone isn't sufficient to attempt a live call."""

    def test_neither_set_is_unconfigured(self, monkeypatch):
        assert CJDropshippingClient().is_configured() is False

    def test_api_key_only_is_unconfigured(self, monkeypatch):
        monkeypatch.setenv("CJ_API_KEY", "fake")
        assert CJDropshippingClient().is_configured() is False

    def test_email_only_is_unconfigured(self, monkeypatch):
        monkeypatch.setenv("CJ_EMAIL", "ops@example.com")
        assert CJDropshippingClient().is_configured() is False

    def test_both_set_is_configured(self, monkeypatch):
        monkeypatch.setenv("CJ_API_KEY", "fake")
        monkeypatch.setenv("CJ_EMAIL", "ops@example.com")
        assert CJDropshippingClient().is_configured() is True


class TestCJTokenManager:
    def _manager(self):
        import backend.validation.suppliers as sup_mod
        return sup_mod._CJTokenManager()

    def test_authenticates_when_no_cached_token(self, monkeypatch):
        monkeypatch.setenv("CJ_API_KEY", "fake")
        monkeypatch.setenv("CJ_EMAIL", "ops@example.com")
        calls = []

        class _FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"data": {"accessToken": "at_1", "refreshToken": "rt_1",
                                "accessTokenExpiryDate": "2999-01-01 00:00:00",
                                "refreshTokenExpiryDate": "2999-06-01 00:00:00"}}

        monkeypatch.setattr("requests.post", lambda url, **kw: calls.append(url) or _FakeResponse())
        manager = self._manager()
        token = manager.access_token()
        assert token == "at_1"
        assert len(calls) == 1
        assert "getAccessToken" in calls[0]

    def test_cached_token_reused_without_reauthenticating(self, monkeypatch):
        monkeypatch.setenv("CJ_API_KEY", "fake")
        monkeypatch.setenv("CJ_EMAIL", "ops@example.com")
        manager = self._manager()
        manager._access_token = "cached_token"
        import time
        manager._access_expiry = time.time() + 999999

        monkeypatch.setattr("requests.post",
                           lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not auth")))
        assert manager.access_token() == "cached_token"

    def test_expiring_token_triggers_refresh_not_full_reauth(self, monkeypatch):
        monkeypatch.setenv("CJ_API_KEY", "fake")
        monkeypatch.setenv("CJ_EMAIL", "ops@example.com")
        manager = self._manager()
        import time
        manager._access_token = "stale_token"
        manager._access_expiry = time.time() + 10  # inside the refresh margin
        manager._refresh_token = "rt_1"
        manager._refresh_expiry = time.time() + 999999

        calls = []

        class _FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"data": {"accessToken": "at_refreshed",
                                "accessTokenExpiryDate": "2999-01-01 00:00:00"}}

        monkeypatch.setattr("requests.post", lambda url, **kw: calls.append(url) or _FakeResponse())
        token = manager.access_token()
        assert token == "at_refreshed"
        assert len(calls) == 1
        assert "refreshAccessToken" in calls[0]

    def test_expired_refresh_token_falls_back_to_full_reauth(self, monkeypatch):
        monkeypatch.setenv("CJ_API_KEY", "fake")
        monkeypatch.setenv("CJ_EMAIL", "ops@example.com")
        manager = self._manager()
        import time
        manager._access_token = "stale_token"
        manager._access_expiry = time.time() + 10
        manager._refresh_token = "rt_expired"
        manager._refresh_expiry = time.time() - 100  # already expired

        calls = []

        class _FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"data": {"accessToken": "at_fresh", "refreshToken": "rt_fresh",
                                "accessTokenExpiryDate": "2999-01-01 00:00:00",
                                "refreshTokenExpiryDate": "2999-06-01 00:00:00"}}

        monkeypatch.setattr("requests.post", lambda url, **kw: calls.append(url) or _FakeResponse())
        token = manager.access_token()
        assert token == "at_fresh"
        assert "getAccessToken" in calls[0]  # full re-auth, not refresh


class TestCJOrderIdempotency:
    def test_existing_order_skips_create_call(self, monkeypatch):
        monkeypatch.setenv("SUPPLIER_ORDERS_DRY_RUN", "false")
        monkeypatch.setenv("CJ_API_KEY", "fake")
        monkeypatch.setenv("CJ_EMAIL", "ops@example.com")
        import backend.validation.suppliers as sup_mod
        monkeypatch.setattr(sup_mod, "_cj_token_manager", sup_mod._CJTokenManager())
        monkeypatch.setattr(sup_mod._cj_token_manager, "access_token", lambda: "fake_token")

        create_calls = []

        class _ExistingResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"data": {"list": [{"orderId": "cj_existing_1"}]}}

        monkeypatch.setattr("requests.get", lambda *a, **kw: _ExistingResponse())
        monkeypatch.setattr("requests.post",
                           lambda *a, **kw: create_calls.append(1) or (_ for _ in ()).throw(
                               AssertionError("createOrder should not be called")))

        client = CJDropshippingClient()
        result = client._live_place_order(_order("order_1"))
        assert result["status"] == "ok"
        assert result["supplier_order_id"] == "cj_existing_1"
        assert create_calls == []

    def test_no_existing_order_creates_new_one(self, monkeypatch):
        monkeypatch.setenv("SUPPLIER_ORDERS_DRY_RUN", "false")
        monkeypatch.setenv("CJ_API_KEY", "fake")
        monkeypatch.setenv("CJ_EMAIL", "ops@example.com")
        import backend.validation.suppliers as sup_mod
        monkeypatch.setattr(sup_mod, "_cj_token_manager", sup_mod._CJTokenManager())
        monkeypatch.setattr(sup_mod._cj_token_manager, "access_token", lambda: "fake_token")

        class _EmptyResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"data": {"list": []}}

        class _CreatedResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"data": {"orderId": "cj_new_1"}}

        monkeypatch.setattr("requests.get", lambda *a, **kw: _EmptyResponse())
        monkeypatch.setattr("requests.post", lambda *a, **kw: _CreatedResponse())

        client = CJDropshippingClient()
        result = client._live_place_order(_order("order_2"))
        assert result["status"] == "ok"
        assert result["supplier_order_id"] == "cj_new_1"

    def test_lookup_failure_falls_through_to_create(self, monkeypatch):
        monkeypatch.setenv("SUPPLIER_ORDERS_DRY_RUN", "false")
        monkeypatch.setenv("CJ_API_KEY", "fake")
        monkeypatch.setenv("CJ_EMAIL", "ops@example.com")
        import backend.validation.suppliers as sup_mod
        monkeypatch.setattr(sup_mod, "_cj_token_manager", sup_mod._CJTokenManager())
        monkeypatch.setattr(sup_mod._cj_token_manager, "access_token", lambda: "fake_token")

        class _CreatedResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"data": {"orderId": "cj_new_2"}}

        monkeypatch.setattr("requests.get",
                           lambda *a, **kw: (_ for _ in ()).throw(ConnectionError("down")))
        monkeypatch.setattr("requests.post", lambda *a, **kw: _CreatedResponse())

        client = CJDropshippingClient()
        result = client._live_place_order(_order("order_3"))
        assert result["status"] == "ok"
        assert result["supplier_order_id"] == "cj_new_2"
