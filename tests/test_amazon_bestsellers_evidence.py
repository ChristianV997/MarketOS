"""Focused evidence tests for the scrape-disabled Amazon bestsellers adapter."""
from __future__ import annotations

import json
import os

import pytest

from backend.adapters import amazon_bestsellers as mod
from backend.adapters.amazon_bestsellers import (
    FIXTURE_SOURCE,
    LIVE_FLAG,
    collect_amazon_bestseller_evidence,
    explain_amazon_bestsellers_readiness,
    fetch,
    normalize_rank_record,
    register,
)


@pytest.fixture(autouse=True)
def _clear_cache(monkeypatch):
    monkeypatch.setattr(mod, "_CACHE", [])
    monkeypatch.setattr(mod, "_CACHE_TS", 0.0)
    monkeypatch.delenv(LIVE_FLAG, raising=False)
    monkeypatch.delenv("MARKETOS_AMAZON_BESTSELLERS_PROVIDER", raising=False)


def test_fetch_returns_empty_non_authoritative_list():
    rows = fetch()
    assert rows == []
    assert not any(row.get("source") == FIXTURE_SOURCE for row in rows)
    assert not any(row.get("source") == "amazon_bestsellers_mock" for row in rows)


def test_fetch_does_not_emit_fixture_product_score_rows():
    rows = fetch()
    assert isinstance(rows, list)
    assert len(rows) == 0
    # Explicit regression: no product/score payloads on the SignalEngine path.
    assert not any("product" in row and "score" in row for row in rows)


def test_fetch_does_not_call_requests_or_parse_html(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("network or html path must not run")

    monkeypatch.setitem(os.environ, "AMAZON_BESTSELLER_CATEGORIES", "electronics")
    monkeypatch.setattr(mod, "_CACHE", [])
    monkeypatch.setattr(mod, "_CACHE_TS", 0.0)
    # If legacy helpers were reintroduced, these would fail loudly.
    if hasattr(mod, "_fetch_category"):
        monkeypatch.setattr(mod, "_fetch_category", boom)
    if hasattr(mod, "_parse_page"):
        monkeypatch.setattr(mod, "_parse_page", boom)
    monkeypatch.setitem(__import__("sys").modules, "requests", type("R", (), {"get": staticmethod(boom)})())
    rows = fetch()
    assert rows == []


def test_fetch_cache_round_trip():
    first = fetch()
    second = fetch()
    assert first == []
    assert first is second


def test_collect_fixture_still_returns_labeled_non_live_rows():
    result = collect_amazon_bestseller_evidence(mode="fixture", allow_network=False)
    assert result["status"] == "fixture"
    assert result["evidence_mode"] == "fixture"
    assert result["live_validated"] is False
    assert result["network_calls"] is False
    assert result["records"]
    assert all(row["source"] == FIXTURE_SOURCE for row in result["records"])
    assert all(row["evidence_mode"] == "fixture" for row in result["records"])
    assert all(row["live_validated"] is False for row in result["records"])
    assert all(row["rank_semantics"] == "relative_bestseller_rank_not_unit_sales" for row in result["records"])
    assert all(row.get("price") is None for row in result["records"])
    assert all(row.get("currency") is None for row in result["records"])
    assert "signalengine_fetch_returns_empty_non_authoritative_list" in result["warnings"]


def test_register_with_signal_engine_does_not_surface_amazon_fixture_scores():
    from core.signals import SignalEngine

    engine = SignalEngine()
    register(engine)
    assert any(item["name"] == "amazon_bestsellers" for item in engine._sources)
    aggregated = engine.get(force_refresh=True)
    # Engine may fall back to generic mock when all sources are empty; those
    # must not be amazon fixture product scores from this adapter.
    assert not any(row.get("source") == FIXTURE_SOURCE for row in aggregated)
    assert not any(row.get("source") == "amazon_bestsellers_mock" for row in aggregated)
    assert not any(
        row.get("source") == "amazon_bestsellers" and row.get("evidence_mode") == "fixture"
        for row in aggregated
    )


def test_readiness_live_gate_blocked_by_default():
    readiness = explain_amazon_bestsellers_readiness(allow_network=False)
    assert readiness["html_scraping"] is False
    assert readiness["live_flag_enabled"] is False
    assert readiness["status"] == "fixture_only"
    assert "html_bestseller_scrape_disabled" in readiness["blockers"]
    assert readiness["unsupported"]["ungated_live_bestseller_browse"] is True


def test_live_mode_without_transport_is_blocked(monkeypatch):
    monkeypatch.setenv(LIVE_FLAG, "1")
    result = collect_amazon_bestseller_evidence(mode="live", allow_network=True)
    assert result["status"] == "blocked"
    assert result["records"] == []
    assert result["network_calls"] is False
    assert result["live_validated"] is False
    assert "injected_transport_required" in result["blockers"]


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
    assert "live_provider_calls_not_enabled_in_this_lane" in result["blockers"]


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
                        # rank missing on purpose
                        "price": 5,
                        # currency missing -> price must not be invented through
                    },
                    {"rank": 1},  # missing product -> skipped
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
    by_title = {row["product"]: row for row in result["records"]}
    assert by_title["Portable Blender"]["rank"] == 3
    assert by_title["Portable Blender"]["price"] == 19.99
    assert by_title["Portable Blender"]["currency"] == "USD"
    assert by_title["Portable Blender"]["availability"] == "in_stock"
    assert by_title["Missing Rank Item"]["rank"] is None
    assert by_title["Missing Rank Item"]["price"] is None
    assert by_title["Missing Rank Item"]["currency"] is None
    assert by_title["Explicit Zero Rank"]["rank"] == 0
    assert by_title["Explicit Zero Rank"]["score"] == 0.0
    assert result["record_count"] == 3
    assert all("product" in row and row["product"] for row in result["records"])


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
        assert "sales_volume" not in row
        assert "unit_sales" not in row
        assert "estimated_units" not in row
        assert "units_sold" not in row
        assert "demand_proof" not in row
        assert "profit" not in row
        assert "revenue" not in row
        assert "gmv" not in row
        assert "launch_authority" not in row
        assert "observed" not in row

    collect = collect_amazon_bestseller_evidence(
        mode="manual_import",
        manual_rows=[injected],
    )
    assert collect["records"]
    assert all(row["live_validated"] is False for row in collect["records"])
    assert all("sales_volume" not in row for row in collect["records"])
    assert all("unit_sales" not in row for row in collect["records"])
