"""Tests for signal adapters (amazon_bestsellers, tiktok_organic)."""
import pytest
from unittest.mock import patch


def test_amazon_fetch_returns_mock_when_network_unavailable():
    from backend.adapters.amazon_bestsellers import fetch
    # Force a fresh cache miss with no network
    import backend.adapters.amazon_bestsellers as mod
    mod._CACHE = []
    mod._CACHE_TS = 0.0
    with patch("requests.get", side_effect=Exception("no network")):
        results = fetch()
    assert isinstance(results, list)
    assert len(results) > 0
    assert all("product" in r for r in results)
    assert all("score" in r for r in results)


def test_amazon_fetch_cached():
    from backend.adapters.amazon_bestsellers import fetch
    import backend.adapters.amazon_bestsellers as mod
    import time
    sentinel = [{"product": "cached_item", "score": 0.9, "source": "test"}]
    mod._CACHE = sentinel
    mod._CACHE_TS = time.time()
    results = fetch()
    assert results is sentinel


def test_amazon_register():
    from backend.adapters.amazon_bestsellers import register
    from core.signals import SignalEngine
    engine = SignalEngine()
    register(engine)
    assert any(s["name"] == "amazon_bestsellers" for s in engine._sources)


def test_tiktok_fetch_returns_mock_when_no_credentials():
    import backend.adapters.tiktok_organic as mod
    mod._CACHE = []
    mod._CACHE_TS = 0.0
    mod._ACCESS_TOKEN = ""
    results = mod.fetch()
    assert isinstance(results, list)
    assert len(results) > 0
    assert all("product" in r for r in results)
    assert all("score" in r for r in results)


def test_tiktok_register():
    from backend.adapters.tiktok_organic import register
    from core.signals import SignalEngine
    engine = SignalEngine()
    register(engine)
    assert any(s["name"] == "tiktok_organic" for s in engine._sources)


def test_signal_engine_with_adapters():
    from core.signals import SignalEngine
    import backend.adapters.amazon_bestsellers as amz_mod
    import backend.adapters.tiktok_organic as ttk_mod

    # Reset caches so fetch functions are called fresh
    amz_mod._CACHE = []
    amz_mod._CACHE_TS = 0.0
    ttk_mod._CACHE = []
    ttk_mod._CACHE_TS = 0.0

    amz_data = [{"product": "test_amz", "score": 0.8, "source": "amazon_bestsellers"}]
    ttk_data = [{"product": "test_ttk", "score": 0.9, "source": "tiktok_organic"}]

    engine = SignalEngine()
    engine.register_source("amazon_bestsellers", lambda: amz_data)
    engine.register_source("tiktok_organic",    lambda: ttk_data)

    signals = engine.get()
    assert len(signals) == 2
    sources = {s["source"] for s in signals}
    assert "amazon_bestsellers" in sources
    assert "tiktok_organic" in sources


def test_google_trends_fetch_maps_topic_to_product():
    """Regression test: the old inline closure in core/signals.py called
    .keyword/.confidence/.velocity as attributes on a dict returned by
    to_canonical() (which has no .keyword — the real key is "topic"),
    raising AttributeError on every call and silently contributing zero
    signals. fetch_google_trends_signals() must map fields via dict access."""
    import backend.adapters.research.trend_source_v1 as mod

    mod._CACHE = []
    mod._CACHE_TS = 0.0

    fixture_raw = [
        {
            "title": {"query": "best buy laptop deals"},
            "formattedTraffic": "200K+",
            "articles": [{"title": "a"}, {"title": "b"}],
        }
    ]

    with patch.object(mod.GoogleTrendsAdapterV1, "fetch", return_value=fixture_raw):
        results = mod.fetch_google_trends_signals()

    assert isinstance(results, list)
    assert len(results) == 1
    assert results[0]["product"] == "best buy laptop deals"
    assert results[0]["source"] == "google_trends"
    assert results[0]["platform"] == "google"
    assert 0.0 <= results[0]["velocity"] <= 1.0
    assert "score" in results[0]


def test_google_trends_fetch_returns_empty_on_network_failure():
    import backend.adapters.research.trend_source_v1 as mod

    mod._CACHE = []
    mod._CACHE_TS = 0.0

    with patch.object(mod.GoogleTrendsAdapterV1, "fetch", side_effect=Exception("no network")):
        results = mod.fetch_google_trends_signals()

    assert results == []


def test_google_trends_register():
    from backend.adapters.research.trend_source_v1 import register
    from core.signals import SignalEngine

    engine = SignalEngine()
    register(engine)
    assert any(s["name"] == "google_trends" for s in engine._sources)


def test_mercadolibre_fetch_shape(monkeypatch):
    import backend.adapters.mercadolibre_trends as mod

    mod._CACHE = []
    mod._CACHE_TS = 0.0
    mod._SITES = ["MLA"]
    mod._QUERIES = ["electronica"]

    fixture_response = {
        "results": [
            {
                "title": "Auriculares Bluetooth Inalambricos",
                "price": 4500.0,
                "sold_quantity": 320,
                "available_quantity": 500,
                "permalink": "https://articulo.mercadolibre.com.ar/MLA-123",
                "category_id": "MLA1000",
            }
        ]
    }

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return fixture_response

    with patch("requests.get", return_value=FakeResponse()):
        results = mod.fetch()

    assert isinstance(results, list)
    assert len(results) == 1
    r = results[0]
    assert r["product"] == "Auriculares Bluetooth Inalambricos"
    assert r["source"] == "mercadolibre"
    assert r["platform"] == "mercadolibre"
    assert r["market"] == "MLA"
    assert 0.0 <= r["score"] <= 1.0
    assert 0.0 <= r["velocity"] <= 1.0


def test_mercadolibre_fetch_returns_empty_on_network_failure():
    import backend.adapters.mercadolibre_trends as mod

    mod._CACHE = []
    mod._CACHE_TS = 0.0

    with patch("requests.get", side_effect=Exception("no network")):
        results = mod.fetch()

    assert results == []


def test_mercadolibre_register():
    from backend.adapters.mercadolibre_trends import register
    from core.signals import SignalEngine

    engine = SignalEngine()
    register(engine)
    assert any(s["name"] == "mercadolibre" for s in engine._sources)


def test_alibaba_fetch_returns_mock_tagged_data():
    from backend.adapters.alibaba_trends import fetch

    results = fetch()
    assert isinstance(results, list)
    assert len(results) > 0
    assert all(r["source"] == "alibaba_mock" for r in results)
    assert all(r["confidence_tier"] == "mock_only" for r in results)
    assert all("product" in r and "score" in r for r in results)


def test_alibaba_register():
    from backend.adapters.alibaba_trends import register
    from core.signals import SignalEngine

    engine = SignalEngine()
    register(engine)
    assert any(s["name"] == "alibaba" for s in engine._sources)


def test_top_opportunities_ranked():
    from core.signals import SignalEngine
    engine = SignalEngine()
    signals = [
        {"product": "a", "score": 0.3},
        {"product": "b", "score": 0.9},
        {"product": "c", "score": 0.6},
    ]
    top = engine.top_opportunities(signals, n=2)
    assert top[0]["product"] == "b"
    assert top[1]["product"] == "c"
