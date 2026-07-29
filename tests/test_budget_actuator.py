"""Tests for backend.optimization.budget_actuator — turning a scaling
decision into a real (or risk-gate-blocked) platform action."""
import pytest


def _decision(campaign_id="c1", platform="tiktok", action="kill",
             current_budget=40.0, new_budget=0.0):
    return {"campaign_id": campaign_id, "platform": platform, "action": action,
           "current_budget": current_budget, "new_budget": new_budget}


class TestApplyDecision:
    def test_maintain_is_skipped(self):
        from backend.optimization.budget_actuator import apply_decision
        result = apply_decision(_decision(action="maintain"))
        assert result["status"] == "skipped"

    def test_missing_campaign_id_is_skipped(self):
        from backend.optimization.budget_actuator import apply_decision
        result = apply_decision(_decision(campaign_id="", action="kill"))
        assert result["status"] == "skipped"

    def test_unknown_platform_is_an_error(self):
        from backend.optimization.budget_actuator import apply_decision
        result = apply_decision(_decision(platform="bogus", action="kill"))
        assert result["status"] == "error"
        assert "unknown_platform" in result["error"]

    def test_meta_scale_without_adgroup_id_is_an_error(self):
        from backend.optimization.budget_actuator import apply_decision
        result = apply_decision(_decision(platform="meta", action="scale_up",
                                          new_budget=60.0))
        assert result["status"] == "error"
        assert result["error"] == "missing_adgroup_id"

    def test_tiktok_kill_calls_pause_campaign(self, monkeypatch):
        calls = []
        monkeypatch.setattr("backend.integrations.tiktok_ads.pause_campaign",
                           lambda cid: calls.append(cid) or True)
        from backend.optimization.budget_actuator import apply_decision
        result = apply_decision(_decision(platform="tiktok", action="kill", campaign_id="c1"))
        assert result["status"] == "ok"
        assert calls == ["c1"]

    def test_tiktok_scale_calls_scale_budget_with_current_budget(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            "backend.integrations.tiktok_ads.scale_budget",
            lambda cid, new_budget, current_budget=0.0: calls.append(
                (cid, new_budget, current_budget)) or True,
        )
        from backend.optimization.budget_actuator import apply_decision
        result = apply_decision(_decision(platform="tiktok", action="scale_up",
                                          current_budget=40.0, new_budget=48.0))
        assert result["status"] == "ok"
        assert calls == [("c1", 48.0, 40.0)]

    def test_meta_kill_calls_pause_campaign(self, monkeypatch):
        calls = []
        monkeypatch.setattr("backend.integrations.meta_ads_client.pause_campaign",
                           lambda cid: calls.append(cid) or True)
        from backend.optimization.budget_actuator import apply_decision
        result = apply_decision(_decision(platform="meta", action="kill", campaign_id="camp_1"))
        assert result["status"] == "ok"
        assert calls == ["camp_1"]

    def test_meta_scale_calls_update_ad_set_budget_with_adgroup_id(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            "backend.integrations.meta_ads_client.update_ad_set_budget",
            lambda asid, new_budget, current_budget=0.0: calls.append(
                (asid, new_budget, current_budget)) or True,
        )
        from backend.optimization.budget_actuator import apply_decision
        result = apply_decision(
            _decision(platform="meta", action="scale_up", current_budget=40.0, new_budget=48.0),
            adgroup_id="as_1",
        )
        assert result["status"] == "ok"
        assert calls == [("as_1", 48.0, 40.0)]

    def test_actuation_exception_is_caught_and_reported(self, monkeypatch):
        def boom(cid):
            raise RuntimeError("platform API down")
        monkeypatch.setattr("backend.integrations.tiktok_ads.pause_campaign", boom)
        from backend.optimization.budget_actuator import apply_decision
        result = apply_decision(_decision(platform="tiktok", action="kill"))
        assert result["status"] == "error"
        assert "platform API down" in result["error"]


class TestApplyDecisionsLive:
    def test_summarizes_across_decisions(self, monkeypatch):
        monkeypatch.setattr("backend.integrations.tiktok_ads.pause_campaign", lambda cid: True)
        monkeypatch.setattr(
            "backend.integrations.meta_ads_client.update_ad_set_budget",
            lambda asid, new_budget, current_budget=0.0: True,
        )
        from backend.optimization.budget_actuator import apply_decisions_live
        decisions = [
            _decision(campaign_id="c1", platform="tiktok", action="kill"),
            _decision(campaign_id="c2", platform="meta", action="scale_up",
                     current_budget=40.0, new_budget=48.0),
        ]
        result = apply_decisions_live(decisions, adgroup_ids={"c2": "as_2"})
        assert result["total"] == 2
        assert result["applied"] == 2
        assert result["errors"] == 0
