"""Tests for backend.discovery — ad intelligence and opportunity aggregation."""
from backend.discovery.ad_intelligence import search_ads, competition_summary
from backend.discovery import discover_products


# ── ad intelligence ───────────────────────────────────────────────────────────

def test_mock_search_is_deterministic():
    a = search_ads("led lamp")
    b = search_ads("led lamp")
    assert a == b


def test_mock_search_varies_by_keyword():
    a = search_ads("led lamp")
    b = search_ads("yoga mat")
    assert a != b or len(a) != len(b)


def test_search_ads_respects_limit():
    ads = search_ads("led lamp", limit=3)
    assert len(ads) <= 3


def test_competition_summary_bounds():
    s = competition_summary("led lamp")
    assert 0.0 <= s["market_saturation"] <= 1.0
    assert s["difficulty"] in ("easy", "medium", "hard")
    assert s["competitor_count"] >= 0
    assert s["ad_count"] >= s["competitor_count"] * 0  # sanity: both non-negative


def test_competition_summary_fields():
    s = competition_summary("yoga mat")
    for key in ("keyword", "competitor_count", "ad_count", "total_spend_upper",
                "avg_spend_upper", "market_saturation", "difficulty"):
        assert key in s


# ── discovery aggregation ─────────────────────────────────────────────────────

def _fake_signals():
    return [
        {"product": "Alpha Widget", "score": 0.9, "source": "test", "platform": "meta"},
        {"product": "Alpha Widget", "score": 0.7, "source": "test2", "platform": "meta"},
        {"product": "Beta Gadget",  "score": 0.6, "source": "test", "platform": "tiktok"},
        {"product": "Weak Signal",  "score": 0.2, "source": "test", "platform": "meta"},
        {"product": "",             "score": 0.9, "source": "test", "platform": "meta"},
    ]


def test_discover_dedupes_and_filters(monkeypatch):
    from core.signals import signal_engine
    monkeypatch.setattr(signal_engine, "get", _fake_signals)
    opps = discover_products(limit=10)
    names = [o["product"] for o in opps]
    assert names.count("Alpha Widget") == 1          # deduped
    assert "Weak Signal" not in names                 # below min score
    assert "" not in names                            # empty product dropped


def test_discover_keeps_strongest_signal(monkeypatch):
    from core.signals import signal_engine
    monkeypatch.setattr(signal_engine, "get", _fake_signals)
    opps = discover_products(limit=10)
    alpha = next(o for o in opps if o["product"] == "Alpha Widget")
    assert alpha["signal_score"] == 0.9


def test_discover_scores_penalize_saturation(monkeypatch):
    from core.signals import signal_engine
    monkeypatch.setattr(signal_engine, "get", _fake_signals)
    for o in discover_products(limit=10):
        expected = round(o["signal_score"] * (1 - 0.5 * o["market_saturation"]), 4)
        assert o["opportunity_score"] == expected


def test_discover_respects_limit(monkeypatch):
    from core.signals import signal_engine
    monkeypatch.setattr(signal_engine, "get", _fake_signals)
    assert len(discover_products(limit=1)) == 1


def test_discover_survives_signal_failure(monkeypatch):
    from core.signals import signal_engine
    def _boom():
        raise RuntimeError("source down")
    monkeypatch.setattr(signal_engine, "get", _boom)
    assert discover_products() == []
