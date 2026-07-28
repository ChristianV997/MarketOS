"""Tests for backend/integrations/adobe_ajo.py"""
import backend.integrations.adobe_ajo as ajo


def test_is_configured_missing(monkeypatch):
    monkeypatch.setattr(ajo, "CLIENT_ID", "")
    monkeypatch.setattr(ajo, "CLIENT_SECRET", "")
    monkeypatch.setattr(ajo, "ORG_ID", "")
    assert ajo.is_configured() is False


def test_is_configured_with_creds(monkeypatch):
    monkeypatch.setattr(ajo, "CLIENT_ID", "cid")
    monkeypatch.setattr(ajo, "CLIENT_SECRET", "csecret")
    monkeypatch.setattr(ajo, "ORG_ID", "org@AdobeOrg")
    assert ajo.is_configured() is True


def test_pause_campaign_fallback(monkeypatch):
    monkeypatch.setattr(ajo, "CLIENT_ID", "")
    monkeypatch.setattr(ajo, "CLIENT_SECRET", "")
    monkeypatch.setattr(ajo, "ORG_ID", "")
    result = ajo.pause_campaign("camp_123")
    assert result["status"] == "paused_mock"
    assert result["campaign_id"] == "camp_123"


def test_scale_campaign_fallback(monkeypatch):
    monkeypatch.setattr(ajo, "CLIENT_ID", "")
    monkeypatch.setattr(ajo, "CLIENT_SECRET", "")
    monkeypatch.setattr(ajo, "ORG_ID", "")
    result = ajo.scale_campaign("camp_456", budget_multiplier=2.0)
    assert result["status"] == "scaled_mock"
    assert result["campaign_id"] == "camp_456"
    assert result["budget_multiplier"] == 2.0


def test_scale_campaign_default_multiplier(monkeypatch):
    monkeypatch.setattr(ajo, "CLIENT_ID", "")
    result = ajo.scale_campaign("camp-002")
    assert result["budget_multiplier"] == 1.5


def test_apply_decision_pause(monkeypatch):
    monkeypatch.setattr(ajo, "CLIENT_ID", "")
    result = ajo.apply_decision("camp_1", "pause")
    assert "paused" in result["status"]


def test_apply_decision_scale(monkeypatch):
    monkeypatch.setattr(ajo, "CLIENT_ID", "")
    result = ajo.apply_decision("camp_2", "scale", budget_multiplier=1.5)
    assert "scaled" in result["status"]
    assert result["budget_multiplier"] == 1.5


def test_apply_decision_hold(monkeypatch):
    monkeypatch.setattr(ajo, "CLIENT_ID", "")
    result = ajo.apply_decision("camp_3", "hold")
    assert result["status"] == "hold"


def test_apply_decision_unknown_action(monkeypatch):
    monkeypatch.setattr(ajo, "CLIENT_ID", "")
    result = ajo.apply_decision("camp_4", "unknown_action")
    assert result["status"] == "hold"
