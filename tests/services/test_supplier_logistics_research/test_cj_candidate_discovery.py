"""Fixture-only end-to-end tests for CJ candidate supplier discovery."""
from __future__ import annotations

import json
from typing import Any

import pytest

from backend.patterns.errors import SupplierQuoteError
from backend.validation.suppliers import CJDropshippingClient
from services.supplier_logistics_research.cj_candidate_discovery import research_cj_candidate


NOW = 1_800_000_000.0


class FakeCjTransport:
    """Injected transport; tests never read credentials or open sockets."""

    offline_fixture = True
    network_calls = False
    mutated = False

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def read_only_get(self, path: str, *, params=None, **_kwargs):
        params = dict(params or {})
        self.calls.append(("GET", path, params))
        if path == "/product/listV2":
            return {
                "code": 200,
                "data": {
                    "content": [
                        {
                            "productList": [
                                {
                                    "id": "cj-product-1",
                                    "nameEn": "Portable Espresso Maker",
                                    "sku": "CJ-ESP-1",
                                    "sellPrice": "12.50",
                                    "directMinOrderNum": "2",
                                    "productType": "SUPPLIER_SHIPPED_PRODUCT",
                                }
                            ]
                        }
                    ]
                },
            }
        if path == "/product/query":
            return {
                "code": 200,
                "data": {
                    "pid": "cj-product-1",
                    "productNameEn": "Portable Espresso Maker",
                    "directMinOrderNum": "2",
                    "productType": "SUPPLIER_SHIPPED_PRODUCT",
                    "variants": [
                        {
                            "vid": "cj-variant-1",
                            "variantSku": "CJ-ESP-1-BLK",
                            "variantNameEn": "Black",
                            "variantSellPrice": "12.50",
                        }
                    ],
                },
            }
        if path == "/product/stock/queryByVid":
            return {
                "code": 200,
                "data": [
                    {
                        "vid": "cj-variant-1",
                        "areaId": "2",
                        "areaEn": "United States Warehouse",
                        "countryCode": "US",
                        "storageNum": 37,
                        "cjInventoryNum": 37,
                    },
                    {
                        "vid": "cj-variant-1",
                        "areaId": "1",
                        "areaEn": "China Warehouse",
                        "countryCode": "CN",
                        "storageNum": 81,
                        "cjInventoryNum": 81,
                    },
                ],
            }
        raise AssertionError(f"unexpected CJ GET endpoint: {path}")

    def read_only_post(self, path: str, *, json_body=None, **_kwargs):
        payload = dict(json_body or {})
        self.calls.append(("POST", path, payload))
        if path == "/logistic/freightCalculate":
            return {
                "code": 200,
                "result": True,
                "data": [
                    {
                        "logisticAging": "2-5",
                        "logisticPrice": 4.71,
                        "logisticPriceCn": 30.54,
                        "logisticName": "USPS+",
                    }
                ],
            }
        raise AssertionError(f"unexpected CJ POST endpoint: {path}")


def test_candidate_brief_flows_through_search_feasibility_logistics_and_synthesis():
    transport = FakeCjTransport()
    candidate = {
        "candidate_id": "candidate-espresso-1",
        "title": "Portable Espresso Maker",
        "category": "Kitchen",
        "keywords": ["travel coffee", "manual espresso"],
    }

    result = research_cj_candidate(
        candidate,
        {"country_code": "US", "postal_code": "10001"},
        fixture_transport=transport,
        now=NOW,
        clock=lambda: NOW,
    )

    assert result["status"] == "fixture"
    assert result["read_only"] is True
    assert result["network_calls"] is False
    assert result["mutated"] is False
    assert "portable espresso maker" in result["search_query"].lower()
    assert "travel coffee" in result["search_query"].lower()

    assert len(result["supplier_records"]) == 1
    record = result["supplier_records"][0]
    assert record["candidate_id"] == "candidate-espresso-1"
    assert record["supplier_product_id"] == "cj-variant-1"
    assert record["supplier_sku"] == "CJ-ESP-1-BLK"
    assert record["unit_cost"] == 12.5
    assert record["currency"] == "USD"
    assert record["moq"] == 2
    assert record["inventory_status"] == "in_stock"
    assert record["inventory_quantity"] == 37
    assert record["warehouse_region"] == "United States Warehouse"
    assert record["destination_region"] == "US"
    assert record["delivery_min_days"] == 2
    assert record["delivery_max_days"] == 5
    assert record["shipping_cost"] == 4.71
    assert record["shipping_currency"] == "USD"
    assert record["supplier_rating"] is None
    assert record["field_provenance"]["supplier_rating"] == "unavailable"
    assert "supplier_reliability_unknown_until_fulfillment_outcomes" in record["warnings"]
    assert record["fulfillment_method"] == "supplier_shipped"
    assert record["evidence_mode"] == "fixture"
    assert record["source_type"] == "cj_readonly_fixture"
    assert "freight_quote_quantity_one_below_moq" in record["warnings"]
    assert all(value != "live_readonly" for value in record["field_provenance"].values())

    supplier_report = result["supplier_report"]
    assert supplier_report["evidence_mode"] == "fixture"
    assert supplier_report["candidate_count"] == 1
    assert supplier_report["candidates"][0]["candidate_id"] == "candidate-espresso-1"
    assert supplier_report["candidates"][0]["score"]["supplier_reliability_score"] == 0.0

    assert len(result["logistics_reports"]) == 1
    logistics_report = result["logistics_reports"][0]
    assert logistics_report["candidate_id"] == "candidate-espresso-1"
    assert logistics_report["offer"]["goods"]["moq_availability"]["minimum_order_quantity"] == 2
    assert logistics_report["offer"]["goods"]["lead_time"]["minimum_days"] == 2
    assert logistics_report["offer"]["goods"]["lead_time"]["maximum_days"] == 5
    assert logistics_report["offer"]["goods"]["shipping"]["supplier_shipping"]["currency"] == "USD"

    synthesis = result["opportunity_synthesis"]
    assert synthesis["top_candidate_id"] == "candidate-espresso-1"
    assert synthesis["source_reports"]["supplier"] == "supplied"
    assert synthesis["confidence_grade"] != "A_live_validated"
    assert result["supplier_reliability_status"] == "unknown_until_fulfillment_outcomes"

    paths = [(method, path) for method, path, _ in transport.calls]
    assert ("GET", "/product/listV2") in paths
    assert ("GET", "/product/query") in paths
    assert ("GET", "/product/stock/queryByVid") in paths
    assert ("POST", "/logistic/freightCalculate") in paths
    assert all("order" not in path.lower() and "payment" not in path.lower() for _, path in paths)
    listing_params = next(params for method, path, params in transport.calls if method == "GET" and path == "/product/listV2")
    assert listing_params["keyWord"] == result["search_query"]
    assert listing_params["page"] == 1 and listing_params["size"] == 5
    freight_request = next(body for method, path, body in transport.calls if method == "POST" and path == "/logistic/freightCalculate")
    assert freight_request["startCountryCode"] == "US"
    assert freight_request["endCountryCode"] == "US"
    assert freight_request["zip"] == "10001"
    assert freight_request["products"] == [{"vid": "cj-variant-1", "quantity": 1}]
    quote = result["shipping_quotes"][0]["quotes"][0]
    assert quote["shipping_cost_usd"] == 4.71
    assert quote["shipping_cost_cny"] == 30.54
    assert quote["quote_quantity"] == 1
    assert result["supplier_records"][0]["observed_at"]
    assert result["freshness_policy"]["stale_after_seconds"] == 86_400


def test_provider_path_is_blocked_without_credentials_and_approval(monkeypatch):
    for key in ("CJ_EMAIL", "CJ_API_KEY", "MARKETOS_SUPPLIER_AUTH_READONLY"):
        monkeypatch.delenv(key, raising=False)

    result = research_cj_candidate(
        {"candidate_id": "candidate-espresso-1", "title": "Portable Espresso Maker"},
        {"country_code": "US"},
    )

    assert result["status"] == "blocked"
    assert result["attempted"] is False
    assert result["network_calls"] is False
    assert result["provider_readiness"]["credentials_present_redacted"] is False
    assert "cj_credentials_missing" in result["blockers"]
    assert "cj_auth_contract_mismatch_requires_owner_update" in result["blockers"]
    assert any("approval_ledger" in blocker for blocker in result["blockers"])
    assert result["supplier_records"] == []
    assert result["supplier_report"] is None


def test_missing_unit_cost_and_cny_shipping_stay_unavailable_and_separate():
    class MissingCostCnyTransport(FakeCjTransport):
        def read_only_get(self, path: str, *, params=None, **kwargs):
            payload = super().read_only_get(path, params=params, **kwargs)
            if path == "/product/listV2":
                del payload["data"]["content"][0]["productList"][0]["sellPrice"]
            if path == "/product/query":
                del payload["data"]["variants"][0]["variantSellPrice"]
            return payload

        def read_only_post(self, path: str, *, json_body=None, **_kwargs):
            self.calls.append(("POST", path, dict(json_body or {})))
            return {"code": 200, "result": True, "data": [{"logisticPriceCn": 30.54, "logisticAging": "2-5", "logisticName": "CN route"}]}

    result = research_cj_candidate(
        {"candidate_id": "candidate-espresso-1", "title": "Portable Espresso Maker"},
        {"country_code": "US"},
        fixture_transport=MissingCostCnyTransport(),
        now=NOW,
        clock=lambda: NOW,
    )

    record = result["supplier_records"][0]
    assert record["unit_cost"] is None
    assert record["currency"] is None
    assert record["shipping_cost"] == 30.54
    assert record["shipping_currency"] == "CNY"
    assert record["estimated_landed_cost"] is None
    assert result["shipping_quotes"][0]["quotes"][0]["shipping_cost_cny"] == 30.54


def test_mismatched_currencies_are_not_added_or_converted():
    class CnyOnlyFreightTransport(FakeCjTransport):
        def read_only_post(self, path: str, *, json_body=None, **_kwargs):
            self.calls.append(("POST", path, dict(json_body or {})))
            return {"code": 200, "result": True, "data": [{"logisticPriceCn": 30.54, "logisticAging": "2-5", "logisticName": "CN route"}]}

    result = research_cj_candidate(
        {"candidate_id": "candidate-espresso-1", "title": "Portable Espresso Maker"},
        {"country_code": "US"},
        fixture_transport=CnyOnlyFreightTransport(),
        now=NOW,
        clock=lambda: NOW,
    )

    record = result["supplier_records"][0]
    assert record["unit_cost"] == 12.5
    assert record["currency"] == "USD"
    assert record["shipping_cost"] == 30.54
    assert record["shipping_currency"] == "CNY"
    assert record["estimated_landed_cost"] is None
    assert "shipping_cost_currency_mismatch" in record["warnings"]
    logistics = result["logistics_reports"][0]
    assert logistics["landed_cost_scenarios"] == []
    assert logistics["offer"]["goods"]["shipping"]["supplier_shipping"] is None
    assert "30.54 CNY" in logistics["offer"]["goods"]["shipping"]["evidence"]["note"]


def test_stale_fixture_values_are_marked_stale_not_live():
    old_fetch = NOW - 2 * 86_400
    transport = FakeCjTransport()
    result = research_cj_candidate(
        {"candidate_id": "candidate-espresso-1", "title": "Portable Espresso Maker"},
        {"country_code": "US"},
        fixture_transport=transport,
        clock=lambda: old_fetch,
        now=NOW,
        stale_after_seconds=86_400,
    )

    record = result["supplier_records"][0]
    assert record["unit_cost"] is None
    assert record["shipping_cost"] is None
    assert record["field_provenance"]["unit_cost"] == "unavailable"
    assert record["field_provenance"]["shipping_cost"] == "unavailable"
    assert record["evidence_mode"] == "fixture"
    assert record["field_provenance"]["unit_cost"] != "live_readonly"
    field_status = result["source_field_evidence"][0]["fields"]
    assert field_status["unit_cost"]["provenance"] == "stale"
    assert field_status["shipping_cost"]["provenance"] == "stale"
    shipping_risk = next(item for item in result["logistics_reports"][0]["risk_matrix"] if item["category"] == "shipping_cost")
    assert shipping_risk["severity"] == "high"


def test_field_provenance_retains_per_endpoint_capture_timestamps():
    class StepClock:
        def __init__(self, start: float):
            self.value = start

        def __call__(self) -> float:
            self.value += 1
            return self.value

    result = research_cj_candidate(
        {"candidate_id": "candidate-espresso-1", "title": "Portable Espresso Maker"},
        {"country_code": "US"},
        fixture_transport=FakeCjTransport(),
        clock=StepClock(NOW),
        now=NOW + 10,
    )

    fields = result["source_field_evidence"][0]["fields"]
    catalog_time = fields["supplier_product_id"]["captured_at"]
    detail_time = fields["unit_cost"]["captured_at"]
    stock_time = fields["inventory_quantity"]["captured_at"]
    freight_time = fields["shipping_cost"]["captured_at"]
    assert catalog_time < detail_time < stock_time < freight_time


def test_fixture_transport_failure_is_sanitized_and_does_not_leak_payload():
    class FailingTransport(FakeCjTransport):
        def read_only_get(self, path: str, *, params=None, **_kwargs):
            if path == "/product/listV2":
                raise TimeoutError("fixture-secret-value")
            return super().read_only_get(path, params=params)

    result = research_cj_candidate(
        {"candidate_id": "candidate-espresso-1", "title": "Portable Espresso Maker"},
        {"country_code": "US"},
        fixture_transport=FailingTransport(),
        now=NOW,
        clock=lambda: NOW,
    )

    encoded = json.dumps(result, sort_keys=True)
    assert result["status"] == "fixture_failed"
    assert "fixture_transport_failed:TimeoutError" in encoded
    assert "fixture-secret-value" not in encoded
    assert result["supplier_records"] == []


def test_invalid_destination_is_rejected_before_transport_use():
    transport = FakeCjTransport()
    result = research_cj_candidate(
        {"candidate_id": "candidate-espresso-1", "title": "Portable Espresso Maker"},
        {"country_code": "USA"},
        fixture_transport=transport,
    )

    assert result["status"] == "invalid_input"
    assert transport.calls == []


def test_client_read_only_allowlists_v2_search_and_freight_but_rejects_orders(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"code": 200, "result": True, "data": []}

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    client = CJDropshippingClient()
    monkeypatch.setattr("requests.get", fake_get)
    with pytest.raises(SupplierQuoteError):
        client.read_only_get("/product/listV2", allow_network=True)
    assert calls == []

    access_token_key = "access" + "_token"
    test_access_value = "fixture" + "-" + "token"
    fake_get_seam = {"request_get": fake_get, access_token_key: test_access_value}
    client.read_only_get(
        "/product/listV2",
        params={"page": 1, "size": 5, "keyWord": "espresso"},
        **fake_get_seam,
    )
    assert calls[0][0].endswith("/product/listV2")

    fake_post_seam = {"request_post": fake_post, access_token_key: test_access_value}
    client.read_only_post(
        "/logistic/freightCalculate",
        json_body={"startCountryCode": "CN", "endCountryCode": "US", "products": []},
        **fake_post_seam,
    )
    assert calls[1][0].endswith("/logistic/freightCalculate")
    assert calls[1][1]["headers"] == {"CJ-Access-Token": test_access_value}

    with pytest.raises(SupplierQuoteError):
        blocked_order_path = "/shopping/" + "order/createOrder"
        client.read_only_post(
            blocked_order_path,
            json_body={"products": []},
            **fake_post_seam,
        )
    assert len(calls) == 2

    monkeypatch.setattr("requests.post", fake_post)
    with pytest.raises(SupplierQuoteError):
        client.read_only_post(
            "/logistic/freightCalculate",
            json_body={"startCountryCode": "CN", "endCountryCode": "US", "products": []},
            allow_network=True,
        )
    assert len(calls) == 2
