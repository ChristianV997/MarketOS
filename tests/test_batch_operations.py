"""Tests for Meta/TikTok batch ad-creation operations."""
import pytest

import backend.integrations.meta_ads_client as meta
import backend.integrations.tiktok_ads as tiktok


class TestMetaBatchAds:
    def test_empty_ads_returns_empty(self):
        assert meta.create_ads_batch("as_1", []) == []

    def test_dry_run_creates_all_ads(self):
        ads = [
            {"name": "ad1", "headline": "Buy now", "body": "hook1", "link_url": "http://x/1"},
            {"name": "ad2", "headline": "Limited", "body": "hook2", "link_url": "http://x/2"},
        ]
        ad_ids = meta.create_ads_batch("as_1", ads)
        assert len(ad_ids) == 2
        assert all(aid for aid in ad_ids)
        assert len(set(ad_ids)) == 2  # unique dry-run ids

    def test_live_batch_request_shape(self, monkeypatch):
        """Live path queues one SDK batch call and parses per-ad responses
        via the success callback (order-preserving), instead of a raw
        Graph API batch POST."""
        monkeypatch.setattr(meta, "AD_ACCOUNT_ID", "123")  # code adds the act_ prefix
        monkeypatch.setenv("META_DRY_RUN", "false")
        monkeypatch.setattr(meta, "_live", lambda: True)
        monkeypatch.setattr(meta, "_ensure_api", lambda: None)

        queued = []

        class FakeResponse:
            def __init__(self, body):
                self._body = body

            def json(self):
                return self._body

        class FakeAd:
            def __init__(self, parent_id=None, fbid=None):
                self.parent_id = parent_id

            def api_create(self, params=None, batch=None, success=None, failure=None):
                queued.append({"parent_id": self.parent_id, "params": params,
                              "success": success, "failure": failure})

        class FakeBatch:
            def execute(self):
                for i, call in enumerate(queued):
                    call["success"](FakeResponse({"id": f"ad_{i + 1}"}))

        class FakeApi:
            def new_batch(self):
                return FakeBatch()

        monkeypatch.setattr(meta, "Ad", FakeAd)
        monkeypatch.setattr(meta.FacebookAdsApi, "get_default_api", staticmethod(lambda: FakeApi()))

        ads = [
            {"name": "ad1", "headline": "H1", "body": "B1", "link_url": "http://x/1"},
            {"name": "ad2", "headline": "H2", "body": "B2", "link_url": "http://x/2"},
        ]
        ad_ids = meta.create_ads_batch("as_1", ads)

        assert ad_ids == ["ad_1", "ad_2"]
        assert len(queued) == 2
        assert all(q["parent_id"] == "act_123" for q in queued)
        assert all(q["params"]["adset_id"] == "as_1" for q in queued)

    def test_live_batch_failure_returns_empty_list(self, monkeypatch):
        monkeypatch.setattr(meta, "AD_ACCOUNT_ID", "123")
        monkeypatch.setenv("META_DRY_RUN", "false")
        monkeypatch.setattr(meta, "_live", lambda: True)
        monkeypatch.setattr(meta, "_ensure_api", lambda: None)

        class FakeAd:
            def __init__(self, parent_id=None, fbid=None):
                pass

            def api_create(self, params=None, batch=None, success=None, failure=None):
                pass

        class FakeBatch:
            def execute(self):
                raise ConnectionError("network down")

        class FakeApi:
            def new_batch(self):
                return FakeBatch()

        monkeypatch.setattr(meta, "Ad", FakeAd)
        monkeypatch.setattr(meta.FacebookAdsApi, "get_default_api", staticmethod(lambda: FakeApi()))

        result = meta.create_ads_batch("as_1", [{"name": "a", "headline": "h"}])
        assert result == []  # safe_call default=list -> fresh []


class TestTikTokBatchAds:
    def test_empty_ads_returns_empty(self):
        assert tiktok.create_ads_batch("ag_1", []) == []

    def test_dry_run_creates_all_ads_concurrently(self):
        ads = [
            {"creative_id": "c1", "name": "ad1", "hook": "h1", "angle": "urgency"},
            {"creative_id": "c2", "name": "ad2", "hook": "h2", "angle": "curiosity"},
            {"creative_id": "c3", "name": "ad3", "hook": "h3", "angle": "authority"},
        ]
        ad_ids = tiktok.create_ads_batch("ag_1", ads)
        assert len(ad_ids) == 3
        assert all(aid for aid in ad_ids)

    def test_preserves_order(self):
        ads = [{"creative_id": f"c{i}", "name": f"ad{i}"} for i in range(5)]
        ad_ids = tiktok.create_ads_batch("ag_1", ads)
        assert len(ad_ids) == 5

    def test_partial_failure_does_not_drop_other_ads(self, monkeypatch):
        """One ad failing shouldn't prevent the others from succeeding."""
        real_create_ad = tiktok.create_ad.__wrapped__

        def flaky_create(adgroup_id, creative_id, name, hook="", angle=""):
            if creative_id == "bad":
                raise RuntimeError("simulated failure")
            return real_create_ad(adgroup_id, creative_id, name, hook=hook, angle=angle)

        monkeypatch.setattr(tiktok, "create_ad", tiktok.safe_call(default="")(flaky_create))

        ads = [
            {"creative_id": "good1", "name": "a1"},
            {"creative_id": "bad", "name": "a2"},
            {"creative_id": "good2", "name": "a3"},
        ]
        ad_ids = tiktok.create_ads_batch("ag_1", ads)
        assert len(ad_ids) == 3
        assert ad_ids[1] == ""  # failed ad returns "" but doesn't break the batch
        assert ad_ids[0] and ad_ids[2]
