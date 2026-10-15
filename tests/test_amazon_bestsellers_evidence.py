"""Focused evidence tests for the unavailable Amazon category-bestseller adapter."""
from __future__ import annotations

import json
import os

import pytest

from backend.adapters import amazon_bestsellers as mod
from backend.adapters.amazon_bestsellers import (
    CAPABILITY_DECISION,
    DEMO_FLAG,
    FIXTURE_SOURCE,
    LIVE_FLAG,
    MANUAL_SOURCE,
    OFFLINE_TRANSPORT_SOURCE,
    collect_amazon_bestseller_evidence,
    explain_amazon_bestsellers_readiness,
    fetch,
    last_fetch_status,
    normalize_rank_record,
    register,
)


@pytest.fixture(autouse=True)
def _clear_cache(monkeypatch):
    monkeypatch.setattr(mod, "_CACHE", [])
    monkeypatch.setattr(mod, "_CACHE_TS", 0.0)
    monkeypatch.setattr(
        mod,
        "_LAST_FETCH_STATUS",
        {
            "status": "unavailable",
            "reason_code": CAPABILITY_DECISION["reason_code"],
            "live_validated": False,
            "records_returned": 0,
        },
    )
    monkeypatch.delenv(LIVE_FLAG, raising=False)
    monkeypatch.delenv(DEMO_FLAG, raising=False)
    monkeypatch.delenv("MARKETOS_AMAZON_BESTSELLERS_PROVIDER", raising=False)


def test_fetch_returns_empty_unavailable_and_never_fixtures(monkeypatch):
    monkeypatch.setenv(DEMO_FLAG, "1")
    rows = fetch()
    assert rows == []
    status = last_fetch_status()
    assert status["status"] == "unavailable"
    assert status["live_validated"] is False
    assert status["records_returned"] == 0
    assert status["reason_code"] == "no_documented_category_bestseller_list_api"
    assert not any(row.get("source") == FIXTURE_SOURCE for row in rows)


def test_fetch_does_not_call_requests_or_parse_html(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("network or html path must not run")

    monkeypatch.setitem(os.environ, "AMAZON_BESTSELLER_CATEGORIES", "electronics")
    if hasattr(mod, "_fetch_category"):
        monkeypatch.setattr(mod, "_fetch_category", boom)
    if hasattr(mod, "_parse_page"):
        monkeypatch.setattr(mod, "_parse_page", boom)
    monkeypatch.setitem(__import__("sys").modules, "requests", type("R", (), {"get": staticmethod(boom)})())
    assert fetch() == []


def test_fetch_cache_round_trip():
    first = fetch()
    second = fetch()
    assert first == []
    assert first is second


def test_default_collect_is_unavailable_not_fixture():
    result = collect_amazon_bestseller_evidence()
    assert result["status"] == "unavailable"
    assert result["evidence_mode"] == "unavailable"
    assert result["records"] == []
    assert result["record_count"] == 0
    assert result["live_validated"] is False
    assert result["network_calls"] is False
    assert result["capability_decision"]["category_bestseller_discovery"] == "unavailable"
    assert result["error"]["code"] == "no_documented_category_bestseller_list_api"
    assert "no_documented_category_bestseller_list_api" in result["blockers"]


def test_collect_fixture_requires_explicit_mode_and_stays_non_live():
    result = collect_amazon_bestseller_evidence(mode="fixture", allow_network=False)
    assert result["status"] == "fixture"
    assert result["evidence_mode"] == "fixture"
    assert result["live_validated"] is False
    assert result["network_calls"] is False
    assert result["records"]
    assert all(row["source"] == FIXTURE_SOURCE for row in result["records"])
    assert all(row["authenticity"] == "synthetic_or_unverified_fixture" for row in result["records"])
    assert all(row["live_validated"] is False for row in result["records"])
    assert all(row["rank_semantics"] == "relative_bestseller_rank_not_unit_sales" for row in result["records"])
    assert "explicit_fixture_mode_not_operational_research" in result["warnings"]


def test_register_with_signal_engine_does_not_surface_amazon_fixture_scores():
    from core.signals import SignalEngine

    engine = SignalEngine()
    register(engine)
    assert any(item["name"] == "amazon_bestsellers" for item in engine._sources)
    aggregated = engine.get(force_refresh=True)
    assert not any(row.get("source") == FIXTURE_SOURCE for row in aggregated)
    assert not any(row.get("source") == "amazon_bestsellers_mock" for row in aggregated)
    # All-source-empty may yield generic engine mock — distinct from Amazon observation.
    assert all(row.get("source") != "amazon_bestsellers" for row in aggregated)


def test_readiness_reports_unavailable_capability():
    readiness = explain_amazon_bestsellers_readiness(allow_network=False)
    assert readiness["html_scraping"] is False
    assert readiness["live_flag_enabled"] is False
    assert readiness["status"] == "unavailable_no_category_bestseller_api"
    assert readiness["approval_ledger_authority"] is False
    assert readiness["unsupported"]["ungated_live_category_bestseller_browse"] is True
    assert readiness["unsupported"]["silent_fixture_as_operational_research"] is True
    assert "creators_api_searchitems_sortby_has_no_bestsellers_value" in readiness["blockers"]
    assert "companyos_approval_ledger_provider_call_or_web_data_acquisition" in readiness["live_prerequisites"]


def test_live_mode_without_transport_is_blocked(monkeypatch):
    monkeypatch.setenv(LIVE_FLAG, "1")
    result = collect_amazon_bestseller_evidence(mode="live", allow_network=True)
    assert result["status"] == "blocked"
    assert result["records"] == []
    assert result["network_calls"] is False
    assert result["live_validated"] is False
    assert "injected_transport_required_for_offline_contract_tests_only" in result["blockers"]


def test_live_mode_with_online_transport_stays_blocked(monkeypatch):
    class OnlineTransport:
        offline_fixture = False

        def fetch_catalog_ranks(self, *, limit: int = 50):
            raise AssertionError("must not call non-offline transport")

    monkeypatch.setenv(LIVE_FLAG, "1")
    result = collect_amazon_bestseller_evidence(
        mode="live", allow_network=True, transport=OnlineTransport()
    )
    assert result["status"] == "blocked"
    assert result["records"] == []
    assert "live_provider_http_not_enabled_no_category_bestseller_endpoint" in result["blockers"]


def test_allow_network_alone_does_not_unlock_operational_collect():
    result = collect_amazon_bestseller_evidence(allow_network=True)
    assert result["status"] == "unavailable"
    assert result["records"] == []
    assert result["live_validated"] is False


def test_offline_injected_transport_normalizes_partial_rows(monkeypatch):
    class FakeTransport:
        offline_fixture = True
        network_calls = False
        mutated = False

        def fetch_catalog_ranks(self, *, limit: int = 50):
            return {
                "items": [
                    {
                        "title": "Portable Blender",
                        "category": "kitchen",
                        "rank": 3,
                        "marketplace": "US",
                        "price": 19.99,
                        "currency": "USD",
                        "availability": "in_stock",
                        "product_url": "https://www.amazon.com/dp/B0EXAMPLE",
                    },
                    {
                        "title": "Missing Rank Item",
                        "category": "kitchen",
                        "price": 5,
                    },
                    {"rank": 1},
                    {
                        "title": "Explicit Zero Rank",
                        "rank": 0,
                        "category": "kitchen",
                    },
                ]
            }

    monkeypatch.setenv(LIVE_FLAG, "1")
    result = collect_amazon_bestseller_evidence(
        mode="live", allow_network=True, transport=FakeTransport(), limit=10
    )
    assert result["status"] == "offline_transport"
    assert result["evidence_mode"] == "offline_transport"
    assert result["network_calls"] is False
    assert result["live_validated"] is False
    assert "offline_transport_is_contract_test_not_live_bestseller_discovery" in result["warnings"]
    by_title = {row["product"]: row for row in result["records"]}
    assert by_title["Portable Blender"]["rank"] == 3
    assert by_title["Portable Blender"]["price"] == 19.99
    assert by_title["Portable Blender"]["currency"] == "USD"
    assert by_title["Portable Blender"]["source"] == OFFLINE_TRANSPORT_SOURCE
    assert by_title["Portable Blender"]["authenticity"] == "offline_injected_transport_unverified"
    assert by_title["Missing Rank Item"]["rank"] is None
    assert by_title["Missing Rank Item"]["price"] is None
    assert by_title["Explicit Zero Rank"]["rank"] == 0
    assert by_title["Explicit Zero Rank"]["score"] == 0.0
    assert result["record_count"] == 3


def test_transport_error_does_not_leak_payload(monkeypatch):
    class ExplodingTransport:
        offline_fixture = True

        def fetch_catalog_ranks(self, *, limit: int = 50):
            raise RuntimeError("secret-transport-token-value")

    monkeypatch.setenv(LIVE_FLAG, "1")
    result = collect_amazon_bestseller_evidence(
        mode="live", allow_network=True, transport=ExplodingTransport()
    )
    encoded = json.dumps(result, sort_keys=True)
    assert result["status"] == "transport_failed"
    assert "transport_failed:RuntimeError" in encoded
    assert "secret-transport-token-value" not in encoded


def test_malformed_transport_payload(monkeypatch):
    class BadTransport:
        offline_fixture = True

        def fetch_catalog_ranks(self, *, limit: int = 50):
            return ["not", "an", "object"]

    monkeypatch.setenv(LIVE_FLAG, "1")
    result = collect_amazon_bestseller_evidence(
        mode="live", allow_network=True, transport=BadTransport()
    )
    assert result["status"] == "transport_invalid"
    assert result["records"] == []


def test_manual_import_preserves_marketplace_currency_separation():
    result = collect_amazon_bestseller_evidence(
        mode="manual_import",
        manual_rows=[
            {
                "product": "MX Manual Row",
                "category": "home",
                "rank": 2,
                "marketplace": "MX",
                "price": 199.0,
                "currency": "MXN",
                "observed_at": "2026-10-14T00:00:00Z",
            },
            {
                "product": "US Manual Row",
                "rank": 1,
                "marketplace": "US",
                "price": 20.0,
                "currency": "USD",
            },
        ],
    )
    assert result["status"] == "manual_import"
    assert result["evidence_mode"] == "manual_import"
    markets = {(row["marketplace"], row["currency"]) for row in result["records"]}
    assert ("MX", "MXN") in markets
    assert ("US", "USD") in markets
    assert all(row["live_validated"] is False for row in result["records"])
    assert all(row["source"] == MANUAL_SOURCE for row in result["records"])
    assert all(row["source"] != FIXTURE_SOURCE for row in result["records"])
    assert all(row["authenticity"] == "operator_supplied_unverified" for row in result["records"])


def test_operational_paths_never_emit_fixture_or_live_validated_rows():
    unavailable = collect_amazon_bestseller_evidence()
    blocked = collect_amazon_bestseller_evidence(mode="live", allow_network=True)
    for result in (unavailable, blocked):
        assert result["records"] == []
        assert result["live_validated"] is False
        assert result["status"] in {"unavailable", "blocked"}
    assert fetch() == []
    assert last_fetch_status()["live_validated"] is False


def test_normalize_rejects_boolean_rank_and_keeps_missing_price():
    assert normalize_rank_record({"product": "x", "rank": True}, evidence_mode="fixture") is None
    row = normalize_rank_record(
        {"product": "x", "rank": 4, "price": None, "currency": None},
        evidence_mode="fixture",
        observed_at="2026-10-14T00:00:00Z",
    )
    assert row is not None
    assert row["rank"] == 4
    assert row["price"] is None
    assert row["currency"] is None


def test_fixture_and_manual_cannot_claim_live_validated_or_sales_volume_authority():
    injected = {
        "product": "Injected Authority Row",
        "rank": 2,
        "category": "electronics",
        "live_validated": True,
        "sales_volume": 12000,
        "unit_sales": 5000,
        "estimated_units": 999,
        "units_sold": 100,
        "demand_proof": True,
        "profit": 42.0,
        "revenue": 1000.0,
        "gmv": 2000.0,
        "launch_authority": True,
        "observed": True,
    }
    fixture_row = normalize_rank_record(injected, evidence_mode="fixture", observed_at="2026-10-14T00:00:00Z")
    manual_row = normalize_rank_record(injected, evidence_mode="manual_import", observed_at="2026-10-14T00:00:00Z")
    assert fixture_row is not None and manual_row is not None
    for row in (fixture_row, manual_row):
        assert row["live_validated"] is False
        assert row["rank_semantics"] == "relative_bestseller_rank_not_unit_sales"
        for key in (
            "sales_volume",
            "unit_sales",
            "estimated_units",
            "units_sold",
            "demand_proof",
            "profit",
            "revenue",
            "gmv",
            "launch_authority",
            "observed",
        ):
            assert key not in row

    collect = collect_amazon_bestseller_evidence(mode="manual_import", manual_rows=[injected])
    assert collect["records"]
    assert all(row["live_validated"] is False for row in collect["records"])
    assert all("sales_volume" not in row for row in collect["records"])
