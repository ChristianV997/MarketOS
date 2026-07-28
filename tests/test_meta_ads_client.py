"""Tests for backend.integrations.meta_ads_client.update_ad_set_budget —
Meta's mirror of tiktok_ads.scale_budget (Tier 2)."""
import os

os.environ.setdefault("META_DRY_RUN", "true")


def test_update_ad_set_budget_dry_run():
    from backend.integrations.meta_ads_client import update_ad_set_budget
    result = update_ad_set_budget("as_123", new_budget=60.0, current_budget=40.0)
    assert result is True


class TestCreateAdSetTargeting:
    def test_default_targeting_unchanged(self, monkeypatch):
        import backend.integrations.meta_ads_client as meta
        captured = {}
        monkeypatch.setattr(meta, "_graph_post",
                            lambda path, payload: captured.update(payload) or {"id": "as_1"})
        meta.create_ad_set("camp_1", name="as1")
        import json
        assert json.loads(captured["targeting"]) == {"geo_locations": {"countries": ["US"]}}

    def test_custom_targeting_passed_through(self, monkeypatch):
        import backend.integrations.meta_ads_client as meta
        captured = {}
        monkeypatch.setattr(meta, "_graph_post",
                            lambda path, payload: captured.update(payload) or {"id": "as_1"})
        custom = {"geo_locations": {"countries": ["MX"]}, "age_min": 25, "age_max": 44}
        meta.create_ad_set("camp_1", name="as1", targeting=custom)
        import json
        assert json.loads(captured["targeting"]) == custom


class TestLiveRiskGateWiring:
    def test_live_gates_and_records_only_the_delta(self, monkeypatch):
        import backend.integrations.meta_ads_client as meta
        monkeypatch.setattr(meta, "_is_dry_run", lambda: False)
        monkeypatch.setattr(meta, "_graph_post", lambda path, payload: {"id": path})

        recorded = []
        monkeypatch.setattr("backend.risk.gate.check_spend",
                           lambda amount: recorded.append(("check", amount)) or
                           {"allowed": True, "adjusted_amount": amount})
        monkeypatch.setattr("backend.risk.gate.record_spend",
                           lambda amount: recorded.append(("record", amount)))

        ok = meta.update_ad_set_budget("as_1", new_budget=60.0, current_budget=40.0)
        assert ok is True
        assert recorded == [("check", 20.0), ("record", 20.0)]

    def test_kill_switch_blocks_live_scale_up(self, monkeypatch):
        import backend.integrations.meta_ads_client as meta
        monkeypatch.setattr(meta, "_is_dry_run", lambda: False)
        calls = []
        monkeypatch.setattr(meta, "_graph_post",
                           lambda path, payload: calls.append(payload) or {"id": path})

        from backend.risk.gate import _engine
        _engine().activate_kill_switch(reason="test")
        try:
            ok = meta.update_ad_set_budget("as_1", new_budget=60.0, current_budget=40.0)
        finally:
            _engine().deactivate_kill_switch()

        assert ok is False
        assert calls == []

    def test_scale_down_never_gated(self, monkeypatch):
        import backend.integrations.meta_ads_client as meta
        monkeypatch.setattr(meta, "_is_dry_run", lambda: False)
        monkeypatch.setattr(meta, "_graph_post", lambda path, payload: {"id": path})

        gate_calls = []
        monkeypatch.setattr("backend.risk.gate.check_spend",
                           lambda amount: gate_calls.append(amount) or
                           {"allowed": True, "adjusted_amount": amount})

        ok = meta.update_ad_set_budget("as_1", new_budget=20.0, current_budget=40.0)
        assert ok is True
        assert gate_calls == []
