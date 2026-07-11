from connectors import tiktok_ads


# --- TikTok Ads ---

def test_tiktok_fallback_no_credentials(monkeypatch):
    monkeypatch.setattr(tiktok_ads, "ACCESS_TOKEN", None)
    monkeypatch.setattr(tiktok_ads, "ADVERTISER_ID", None)
    result = tiktok_ads.get_ad_spend(last_n_minutes=10)
    assert result["total_spend"] > 0
    assert len(result["campaigns"]) > 0
    assert result["campaigns"][0]["campaign_id"].startswith("tt_")


def test_tiktok_fallback_no_requests(monkeypatch):
    monkeypatch.setattr(tiktok_ads, "ACCESS_TOKEN", "token")
    monkeypatch.setattr(tiktok_ads, "ADVERTISER_ID", "adv123")
    monkeypatch.setattr(tiktok_ads, "_requests", None)
    result = tiktok_ads.get_ad_spend()
    assert result["total_spend"] > 0


def test_tiktok_result_keys(monkeypatch):
    monkeypatch.setattr(tiktok_ads, "ACCESS_TOKEN", None)
    result = tiktok_ads.get_ad_spend()
    for key in ("campaigns", "total_spend", "since", "until"):
        assert key in result
