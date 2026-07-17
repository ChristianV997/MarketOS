"""Tests for backend.discovery.signal_cache — TTL, bypass, stale fallback."""
import time

import backend.discovery.signal_cache as sc


def _fake_signals():
    return [{"product": "Cached Widget", "score": 0.9, "source": "t", "platform": "meta"}]


def test_ttl_zero_always_fetches_fresh(monkeypatch, tmp_path):
    """TTL 0 (the test-suite default) bypasses the cache entirely."""
    monkeypatch.setattr(sc, "_CACHE_PATH", str(tmp_path / "cache.json"))
    calls = {"n": 0}

    def _get():
        calls["n"] += 1
        return _fake_signals()

    from core.signals import signal_engine
    monkeypatch.setattr(signal_engine, "get", _get)

    sc.get_signals_cached(max_age_hours=0)
    sc.get_signals_cached(max_age_hours=0)
    assert calls["n"] == 2  # no caching happened


def test_cache_hit_within_ttl(monkeypatch, tmp_path):
    monkeypatch.setattr(sc, "_CACHE_PATH", str(tmp_path / "cache.json"))
    calls = {"n": 0}

    def _get():
        calls["n"] += 1
        return _fake_signals()

    from core.signals import signal_engine
    monkeypatch.setattr(signal_engine, "get", _get)

    first = sc.get_signals_cached(max_age_hours=6)
    second = sc.get_signals_cached(max_age_hours=6)
    assert calls["n"] == 1          # second call served from cache
    assert first == second == _fake_signals()


def test_force_refresh_bypasses_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(sc, "_CACHE_PATH", str(tmp_path / "cache.json"))
    calls = {"n": 0}

    def _get():
        calls["n"] += 1
        return _fake_signals()

    from core.signals import signal_engine
    monkeypatch.setattr(signal_engine, "get", _get)

    sc.get_signals_cached(max_age_hours=6)
    sc.get_signals_cached(max_age_hours=6, force_refresh=True)
    assert calls["n"] == 2


def test_stale_fallback_on_fetch_failure(monkeypatch, tmp_path):
    """With caching on, a failed fresh fetch serves the stale snapshot."""
    monkeypatch.setattr(sc, "_CACHE_PATH", str(tmp_path / "cache.json"))

    from core.signals import signal_engine
    monkeypatch.setattr(signal_engine, "get", _fake_signals)
    sc.get_signals_cached(max_age_hours=6)              # warm the cache

    def _boom():
        raise RuntimeError("sources down")
    monkeypatch.setattr(signal_engine, "get", _boom)

    # Even expired (TTL tiny), the stale cache beats an empty result
    time.sleep(0.01)
    got = sc.get_signals_cached(max_age_hours=1e-9)
    assert got == _fake_signals()


def test_ttl_zero_failure_returns_empty(monkeypatch, tmp_path):
    """With caching disabled, failure mirrors a raw fetch: empty list."""
    monkeypatch.setattr(sc, "_CACHE_PATH", str(tmp_path / "cache.json"))

    from core.signals import signal_engine
    monkeypatch.setattr(signal_engine, "get", _fake_signals)
    sc.get_signals_cached(max_age_hours=6)              # cache exists on disk

    def _boom():
        raise RuntimeError("sources down")
    monkeypatch.setattr(signal_engine, "get", _boom)

    assert sc.get_signals_cached(max_age_hours=0) == []


def test_cache_status_lifecycle(monkeypatch, tmp_path):
    monkeypatch.setattr(sc, "_CACHE_PATH", str(tmp_path / "cache.json"))
    assert sc.cache_status()["status"] == "empty"

    from core.signals import signal_engine
    monkeypatch.setattr(signal_engine, "get", _fake_signals)
    sc.get_signals_cached(max_age_hours=6)

    status = sc.cache_status()
    assert status["signals_cached"] == 1
    assert status["age_hours"] < 1

    sc.clear_cache()
    assert sc.cache_status()["status"] == "empty"


def test_discovery_uses_cache_module(monkeypatch):
    """discover_products flows through get_signals_cached."""
    import backend.discovery as disc
    monkeypatch.setattr(
        "backend.discovery.signal_cache.get_signals_cached",
        lambda **kw: [{"product": "Via Cache", "score": 0.9,
                       "source": "t", "platform": "meta"}],
    )
    opps = disc.discover_products(limit=5)
    assert [o["product"] for o in opps] == ["Via Cache"]
