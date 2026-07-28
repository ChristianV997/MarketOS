"""Tests for backend.launch.channel_selector — replaces the hardcoded
55/45 tiktok/meta split with brand-aware channel preferences."""
import pytest


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.delenv("CHANNEL_SELECT_LIVE", raising=False)


class _FakeBrand:
    def __init__(self, brand_id="beauty", channel_preferences=None):
        self.brand_id = brand_id
        self.channel_preferences = channel_preferences or {}


def test_no_brand_returns_legacy_split():
    from backend.launch.channel_selector import select_weights
    weights = select_weights(("tiktok", "meta"))
    assert weights == {"tiktok": pytest.approx(0.55), "meta": pytest.approx(0.45)}


def test_brand_with_no_preferences_returns_legacy_split():
    from backend.launch.channel_selector import select_weights
    weights = select_weights(("tiktok", "meta"), brand=_FakeBrand())
    assert weights == {"tiktok": pytest.approx(0.55), "meta": pytest.approx(0.45)}


def test_flag_off_ignores_brand_preferences_even_when_set(monkeypatch):
    monkeypatch.delenv("CHANNEL_SELECT_LIVE", raising=False)
    from backend.launch.channel_selector import select_weights
    brand = _FakeBrand(channel_preferences={"tiktok": 0.9, "meta": 0.1})
    weights = select_weights(("tiktok", "meta"), brand=brand)
    assert weights == {"tiktok": pytest.approx(0.55), "meta": pytest.approx(0.45)}


def test_flag_on_uses_brand_preferences(monkeypatch):
    monkeypatch.setenv("CHANNEL_SELECT_LIVE", "true")
    from backend.launch.channel_selector import select_weights
    brand = _FakeBrand(channel_preferences={"tiktok": 0.9, "meta": 0.1})
    weights = select_weights(("tiktok", "meta"), brand=brand)
    assert weights == {"tiktok": pytest.approx(0.9), "meta": pytest.approx(0.1)}


def test_flag_on_normalizes_partial_preferences(monkeypatch):
    monkeypatch.setenv("CHANNEL_SELECT_LIVE", "true")
    from backend.launch.channel_selector import select_weights
    brand = _FakeBrand(channel_preferences={"tiktok": 3.0})  # unnormalized, meta missing
    weights = select_weights(("tiktok", "meta"), brand=brand)
    assert sum(weights.values()) == pytest.approx(1.0)
    assert weights["tiktok"] > weights["meta"]


def test_single_platform_gets_full_weight():
    from backend.launch.channel_selector import select_weights
    weights = select_weights(("tiktok",))
    assert weights == {"tiktok": pytest.approx(1.0)}


def test_shadow_journal_always_written(monkeypatch):
    monkeypatch.delenv("CHANNEL_SELECT_LIVE", raising=False)
    from backend.launch.channel_selector import select_weights
    from backend.orchestration.event_store import event_store

    select_weights(("tiktok", "meta"), brand=_FakeBrand())
    events = [e for e in event_store._iter_events()
             if e.get("event") == "shadow_channel_selection"]
    assert events
    assert events[-1]["data"]["live"] is False


class TestLaunchProductUsesChannelSelector:
    def test_brand_preference_shifts_budget_split_when_live(self, monkeypatch):
        from backend.commerce.brands import Brand, BrandRegistry
        import backend.commerce.brands as brands_mod
        from backend.creation.store_builder import build_product
        from backend.launch.orchestrator import launch_product

        registry = BrandRegistry()
        brand = Brand(brand_id="petbrand", name="Pet Co", category="pets",
                      channel_preferences={"tiktok": 0.9, "meta": 0.1})
        registry.upsert(brand)
        monkeypatch.setattr(brands_mod, "brand_registry", registry)

        verdict = {
            "product": "Cat Wand Toy", "ready_for_creation": True,
            "retail_price": 19.99, "category": "pets",
            "supplier": {"supplier": "zendrop", "fulfillment_days": 9},
        }
        build = build_product(verdict, brand=brand)

        monkeypatch.setenv("CHANNEL_SELECT_LIVE", "true")
        try:
            result = launch_product(build, budget_daily=100.0, platforms=("tiktok", "meta"))
        finally:
            monkeypatch.delenv("CHANNEL_SELECT_LIVE", raising=False)

        by_platform = {c["platform"]: c for c in result["campaigns"]}
        assert by_platform["tiktok"]["budget"] > by_platform["meta"]["budget"]
        assert abs(by_platform["tiktok"]["budget"] - 90.0) < 0.5
