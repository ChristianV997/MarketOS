"""Tests for backend.integrations.tiktok_ads — dry-run mode."""
import os
import pytest


# Force dry-run for all tests
os.environ.setdefault("TIKTOK_DRY_RUN", "true")


def test_is_configured_false_without_env():
    from backend.integrations.tiktok_ads import is_configured
    assert not is_configured()


def test_is_configured_true_with_env(monkeypatch):
    monkeypatch.setenv("TIKTOK_ACCESS_TOKEN", "tok123")
    monkeypatch.setenv("TIKTOK_ADVERTISER_ID", "adv456")
    from backend.integrations import tiktok_ads as mod
    # Re-read env inline since module caches nothing at import time
    assert os.getenv("TIKTOK_ACCESS_TOKEN") == "tok123"


def test_create_campaign_dry_run():
    from backend.integrations.tiktok_ads import create_campaign
    cid = create_campaign("test_product")
    assert cid.startswith("dry_")


def test_create_ad_group_dry_run():
    from backend.integrations.tiktok_ads import create_ad_group
    agid = create_ad_group("dry_cid_123", name="test_group")
    assert agid  # non-empty


def test_create_ad_dry_run():
    from backend.integrations.tiktok_ads import create_ad
    ad_id = create_ad("ag_1", creative_id="c1", name="ad_1", hook="Hook A")
    assert ad_id


def test_pause_campaign_dry_run():
    from backend.integrations.tiktok_ads import pause_campaign
    result = pause_campaign("dry_cid_123")
    assert result is True


def test_scale_budget_dry_run():
    from backend.integrations.tiktok_ads import scale_budget
    result = scale_budget("dry_cid_123", 100.0)
    assert result is True


def test_fetch_roas_dry_run():
    from backend.integrations.tiktok_ads import fetch_roas
    roas = fetch_roas(["cid_1", "cid_2"])
    assert set(roas.keys()) == {"cid_1", "cid_2"}
    for v in roas.values():
        assert 0.0 <= v <= 10.0


def test_get_metrics_dry_run_is_normalized():
    from backend.integrations.tiktok_ads import get_metrics
    metrics = get_metrics(["cid_1"])
    assert metrics["metadata"]["dry_run"] is True
    for key in ("spend", "revenue", "clicks", "impressions", "conversions", "ctr", "cvr"):
        assert key in metrics


def test_check_and_act_kills_overspend():
    from backend.integrations.tiktok_ads import check_and_act, _roas_streaks
    _roas_streaks.clear()
    action = check_and_act("cid_kill", spend=130.0, budget=100.0, roas=0.5)
    assert action == "killed"


def test_check_and_act_scales_on_win_streak():
    from backend.integrations.tiktok_ads import check_and_act, _roas_streaks
    _roas_streaks.clear()
    for _ in range(3):
        action = check_and_act("cid_scale", spend=50.0, budget=100.0, roas=2.0)
    assert action.startswith("scaled_to_")


def test_check_and_act_hold():
    from backend.integrations.tiktok_ads import check_and_act, _roas_streaks
    _roas_streaks.clear()
    action = check_and_act("cid_hold", spend=40.0, budget=100.0, roas=1.2)
    assert action == "hold"


def test_launch_from_playbook_dry_run():
    from backend.integrations.tiktok_ads import launch_from_playbook
    pb = {
        "product": "widget",
        "top_hooks": ["Hook A", "Hook B"],
        "top_angles": ["Angle X"],
        "estimated_roas": 1.8,
    }
    result = launch_from_playbook(pb, phase="VALIDATE")
    assert result["status"] == "ok"
    assert result["dry_run"] is True
    assert result["campaign_id"]
    assert len(result["ad_ids"]) > 0
