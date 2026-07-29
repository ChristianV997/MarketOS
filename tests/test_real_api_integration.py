"""Opt-in live-API integration tests.

These only run when real (sandbox) credentials are present in the
environment — in CI and dev machines without credentials every test here
skips.  Run them against a Meta test ad account / TikTok sandbox to verify
auth and payload shapes before flipping DRY_RUN off in production:

    META_DRY_RUN=false META_ACCESS_TOKEN=... META_AD_ACCOUNT_ID=... \
        python -m pytest tests/test_real_api_integration.py -v
"""
import os

import pytest

_HAS_META = bool(os.getenv("META_ACCESS_TOKEN") and os.getenv("META_AD_ACCOUNT_ID")
                 and os.getenv("META_DRY_RUN", "true").lower() == "false")
_HAS_TIKTOK = bool(os.getenv("TIKTOK_ACCESS_TOKEN") and os.getenv("TIKTOK_ADVERTISER_ID")
                   and os.getenv("TIKTOK_DRY_RUN", "true").lower() == "false")
_HAS_SHOPIFY = bool(os.getenv("SHOPIFY_STORE_URL") and os.getenv("SHOPIFY_ACCESS_TOKEN")
                    and os.getenv("SHOPIFY_DRY_RUN", "true").lower() == "false")


@pytest.mark.skipif(not _HAS_META, reason="no live Meta sandbox credentials")
def test_meta_live_campaign_roundtrip():
    """Create a PAUSED campaign on the test ad account and verify a real ID."""
    from backend.integrations import meta_ads_client

    cid = meta_ads_client.create_campaign("marketos_integration_test")
    assert cid and not cid.startswith("dry_"), "expected a real Meta campaign id"

    asid = meta_ads_client.create_ad_set(cid, "marketos_test_adset", daily_budget=1.0)
    assert asid and not asid.startswith("dry_")


@pytest.mark.skipif(not _HAS_META, reason="no live Meta sandbox credentials")
def test_meta_live_spend_fetch():
    from backend.integrations.meta_ads_client import get_ad_spend

    data = get_ad_spend(last_n_minutes=1440)
    assert "campaigns" in data and "total_spend" in data
    assert data["total_spend"] >= 0.0


@pytest.mark.skipif(not _HAS_TIKTOK, reason="no live TikTok sandbox credentials")
def test_tiktok_live_campaign_created():
    from backend.integrations import tiktok_ads

    cid = tiktok_ads.create_campaign(name="marketos_integration_test",
                                     daily_budget=1.0)
    assert cid and not str(cid).startswith("dry"), "expected a real TikTok campaign id"


@pytest.mark.skipif(not _HAS_SHOPIFY, reason="no live Shopify dev-store credentials")
def test_shopify_live_product_created():
    from backend.creation.store_builder import create_product_page

    page = create_product_page("MarketOS Integration Test Product",
                               "<p>integration test — safe to delete</p>", 1.0)
    assert page["status"] == "ok"
    assert page.get("dry_run") is not True
