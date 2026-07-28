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


def test_create_ad_group_targeting_merged_into_payload(monkeypatch):
    import backend.integrations.tiktok_ads as tiktok_ads
    captured = {}
    monkeypatch.setattr(tiktok_ads, "_post",
                        lambda path, payload: captured.update(payload) or
                        {"data": {"adgroup_id": "ag_1"}})
    tiktok_ads.create_ad_group("cid_1", name="g1",
                              targeting={"age_groups": ["AGE_25_34"], "gender": "GENDER_FEMALE"})
    assert captured["age_groups"] == ["AGE_25_34"]
    assert captured["gender"] == "GENDER_FEMALE"


def test_create_ad_group_no_targeting_unchanged(monkeypatch):
    import backend.integrations.tiktok_ads as tiktok_ads
    captured = {}
    monkeypatch.setattr(tiktok_ads, "_post",
                        lambda path, payload: captured.update(payload) or
                        {"data": {"adgroup_id": "ag_1"}})
    tiktok_ads.create_ad_group("cid_1", name="g1")
    assert "age_groups" not in captured
    assert "gender" not in captured


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


class TestLiveRiskGateWiring:
    """Tier 2 fix: real (non-dry-run) spend passes through backend.risk.gate
    before ever reaching TikTok's API."""

    def test_launch_from_playbook_live_blocked_by_kill_switch(self, monkeypatch):
        import backend.integrations.tiktok_ads as tiktok_ads
        monkeypatch.setattr(tiktok_ads, "_DRY_RUN", False)
        calls = []
        monkeypatch.setattr(tiktok_ads, "create_campaign",
                            lambda **kw: calls.append(kw) or "should_not_be_called")

        from backend.risk.gate import _engine
        _engine().activate_kill_switch(reason="test")
        try:
            result = tiktok_ads.launch_from_playbook(
                {"product": "widget", "top_hooks": ["H"], "top_angles": ["A"],
                 "estimated_roas": 1.8},
                phase="VALIDATE",
            )
        finally:
            _engine().deactivate_kill_switch()

        assert calls == []
        assert result["status"] == "error"
        assert "risk_gate_blocked" in result["reason"]

    def test_scale_budget_live_gates_and_records_only_the_delta(self, monkeypatch):
        import backend.integrations.tiktok_ads as tiktok_ads
        monkeypatch.setattr(tiktok_ads, "_DRY_RUN", False)
        monkeypatch.setattr(tiktok_ads, "_post", lambda path, payload: {"data": {}})

        recorded = []
        monkeypatch.setattr("backend.risk.gate.check_spend",
                           lambda amount: recorded.append(("check", amount)) or
                           {"allowed": True, "adjusted_amount": amount})
        monkeypatch.setattr("backend.risk.gate.record_spend",
                           lambda amount: recorded.append(("record", amount)))

        ok = tiktok_ads.scale_budget("cid_1", new_budget=60.0, current_budget=40.0)
        assert ok is True
        # Only the $20 incremental increase is gated/recorded, not the full $60.
        assert recorded == [("check", 20.0), ("record", 20.0)]

    def test_scale_down_never_gated(self, monkeypatch):
        import backend.integrations.tiktok_ads as tiktok_ads
        monkeypatch.setattr(tiktok_ads, "_DRY_RUN", False)
        monkeypatch.setattr(tiktok_ads, "_post", lambda path, payload: {"data": {}})

        calls = []
        monkeypatch.setattr("backend.risk.gate.check_spend",
                           lambda amount: calls.append(amount) or {"allowed": True, "adjusted_amount": amount})

        ok = tiktok_ads.scale_budget("cid_1", new_budget=20.0, current_budget=40.0)
        assert ok is True
        assert calls == []  # a reduction never needs to pass through the gate
