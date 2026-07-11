from backend.integrations import shopify_client
from backend.integrations import meta_ads_client
from backend.core.state import ensure_state_shape
from backend.decision.engine import decide


def test_shopify_orders_fallback_without_credentials(monkeypatch):
    monkeypatch.setattr(shopify_client, "SHOP_URL", None)
    monkeypatch.setattr(shopify_client, "ACCESS_TOKEN", None)
    orders = shopify_client.get_orders(last_n_minutes=10)
    assert len(orders) > 0
    assert "total_price" in orders[0]


def test_meta_ads_fallback_without_credentials(monkeypatch):
    monkeypatch.setattr(meta_ads_client, "ACCESS_TOKEN", None)
    monkeypatch.setattr(meta_ads_client, "AD_ACCOUNT_ID", None)
    ads = meta_ads_client.get_ad_spend(last_n_minutes=10)
    assert ads["total_spend"] > 0
    assert len(ads["campaigns"]) > 0
    assert [c["campaign_id"] for c in ads["campaigns"]] == ["camp_1", "camp_2", "camp_3"]


def test_meta_ads_fallback_without_requests(monkeypatch):
    monkeypatch.setattr(meta_ads_client, "ACCESS_TOKEN", "token")
    monkeypatch.setattr(meta_ads_client, "AD_ACCOUNT_ID", "account")
    monkeypatch.setattr(meta_ads_client, "requests", None)
    ads = meta_ads_client.get_ad_spend(last_n_minutes=10)
    assert ads["total_spend"] > 0
    assert len(ads["campaigns"]) > 0


def test_ensure_state_shape_backfills_legacy_state():
    class LegacyState:
        pass

    state = ensure_state_shape(LegacyState())
    assert hasattr(state, "event_log")
    assert hasattr(state.event_log, "rows")
    assert hasattr(state, "graph")
    assert hasattr(state.graph, "edges")
    assert hasattr(state, "capital")
    assert hasattr(state, "memory")


def test_decide_handles_legacy_state_shape():
    class LegacyState:
        pass

    decisions = decide(LegacyState())
    assert isinstance(decisions, list)
    assert len(decisions) > 0
