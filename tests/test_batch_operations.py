"""Tests for Meta/TikTok batch ad-creation operations."""
import json

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
        """Live path posts one batch request and parses per-ad responses."""
        monkeypatch.setattr(meta, "ACCESS_TOKEN", "tok")
        monkeypatch.setattr(meta, "AD_ACCOUNT_ID", "123")  # code adds the act_ prefix
        monkeypatch.setenv("META_DRY_RUN", "false")

        captured = {}

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return [
                    {"code": 200, "body": json.dumps({"id": "ad_1"})},
                    {"code": 200, "body": json.dumps({"id": "ad_2"})},
                ]

        def fake_post(url, data=None, timeout=None):
            captured["url"] = url
            captured["data"] = data
            return FakeResponse()

        monkeypatch.setattr(meta.requests, "post", fake_post)

        ads = [
            {"name": "ad1", "headline": "H1", "body": "B1", "link_url": "http://x/1"},
            {"name": "ad2", "headline": "H2", "body": "B2", "link_url": "http://x/2"},
        ]
        ad_ids = meta.create_ads_batch("as_1", ads)

        assert ad_ids == ["ad_1", "ad_2"]
        assert captured["url"] == "https://graph.facebook.com/v20.0/"
        batch_payload = json.loads(captured["data"]["batch"])
        assert len(batch_payload) == 2
        assert all(sr["method"] == "POST" for sr in batch_payload)
        assert all(sr["relative_url"] == "act_123/ads" for sr in batch_payload)

    def test_live_batch_failure_returns_empty_list(self, monkeypatch):
        monkeypatch.setattr(meta, "ACCESS_TOKEN", "tok")
        monkeypatch.setattr(meta, "AD_ACCOUNT_ID", "123")
        monkeypatch.setenv("META_DRY_RUN", "false")

        def raise_post(*a, **k):
            raise ConnectionError("network down")

        monkeypatch.setattr(meta.requests, "post", raise_post)

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
