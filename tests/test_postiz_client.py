"""Tests for backend.integrations.postiz_client — dry-run behavior, determinism."""
import pytest

import backend.integrations.postiz_client as postiz


@pytest.fixture(autouse=True)
def _dry_env(monkeypatch):
    monkeypatch.delenv("POSTIZ_URL", raising=False)
    monkeypatch.delenv("POSTIZ_API_KEY", raising=False)
    monkeypatch.delenv("ORGANIC_DRY_RUN", raising=False)
    yield


def test_dry_run_by_default():
    assert postiz.is_configured() is False
    result = postiz.create_post("Check out this product!", platforms=["tiktok"])
    assert result["status"] == "ok"
    assert result["dry_run"] is True
    assert result["post_id"].startswith("dry_post_")


def test_dry_post_ids_unique():
    a = postiz.create_post("same text")
    b = postiz.create_post("same text")
    assert a["post_id"] != b["post_id"]


def test_dry_metrics_deterministic_per_post():
    m1 = postiz.get_post_metrics("post_abc")
    m2 = postiz.get_post_metrics("post_abc")
    assert m1 == m2
    assert m1["dry_run"] is True
    assert m1["impressions"] >= 500
    engaged = m1["likes"] + m1["comments"] + m1["shares"]
    assert 0 < engaged < m1["impressions"]


def test_dry_metrics_differ_across_posts():
    m1 = postiz.get_post_metrics("post_a")
    m2 = postiz.get_post_metrics("post_b")
    assert m1["impressions"] != m2["impressions"]


def test_configured_only_when_url_key_and_flag(monkeypatch):
    monkeypatch.setenv("POSTIZ_URL", "http://localhost:5000")
    monkeypatch.setenv("POSTIZ_API_KEY", "k")
    # ORGANIC_DRY_RUN still defaults true -> not configured
    assert postiz.is_configured() is False
    monkeypatch.setenv("ORGANIC_DRY_RUN", "false")
    assert postiz.is_configured() is True


def test_live_path_without_creds_stays_dry(monkeypatch):
    monkeypatch.setenv("ORGANIC_DRY_RUN", "false")
    # No URL/key -> still dry
    result = postiz.create_post("hello")
    assert result["dry_run"] is True
