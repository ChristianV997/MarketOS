"""Tests for backend/integrations/supabase_client.py"""
import backend.integrations.supabase_client as sc


def test_is_configured_no_env(monkeypatch):
    monkeypatch.setattr(sc, "SUPABASE_URL", "")
    monkeypatch.setattr(sc, "SUPABASE_SERVICE_ROLE_KEY", "")
    assert sc.is_configured() is False


def test_is_configured_with_env(monkeypatch):
    monkeypatch.setattr(sc, "SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setattr(sc, "SUPABASE_SERVICE_ROLE_KEY", "secret")
    assert sc.is_configured() is True


def test_save_state_no_credentials(monkeypatch):
    monkeypatch.setattr(sc, "SUPABASE_URL", "")
    monkeypatch.setattr(sc, "SUPABASE_SERVICE_ROLE_KEY", "")
    assert sc.save_state({"capital": 1000.0}) is False


def test_load_state_no_credentials(monkeypatch):
    monkeypatch.setattr(sc, "SUPABASE_URL", "")
    monkeypatch.setattr(sc, "SUPABASE_SERVICE_ROLE_KEY", "")
    assert sc.load_state() is None


def test_append_events_empty(monkeypatch):
    monkeypatch.setattr(sc, "SUPABASE_URL", "")
    monkeypatch.setattr(sc, "SUPABASE_SERVICE_ROLE_KEY", "")
    assert sc.append_events([]) is True


def test_append_events_no_credentials(monkeypatch):
    monkeypatch.setattr(sc, "SUPABASE_URL", "")
    monkeypatch.setattr(sc, "SUPABASE_SERVICE_ROLE_KEY", "")
    assert sc.append_events([{"roas": 1.2}]) is False


def test_save_state_no_requests(monkeypatch):
    monkeypatch.setattr(sc, "SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setattr(sc, "SUPABASE_SERVICE_ROLE_KEY", "secret")
    monkeypatch.setattr(sc, "_requests", None)
    assert sc.save_state({"capital": 999.0}) is False


def test_load_state_no_requests(monkeypatch):
    monkeypatch.setattr(sc, "SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setattr(sc, "SUPABASE_SERVICE_ROLE_KEY", "secret")
    monkeypatch.setattr(sc, "_requests", None)
    assert sc.load_state() is None


def test_save_cycle_summary_no_credentials(monkeypatch):
    monkeypatch.setattr(sc, "SUPABASE_URL", "")
    monkeypatch.setattr(sc, "SUPABASE_SERVICE_ROLE_KEY", "")
    result = sc.save_cycle_summary({"total_cycles": 1, "capital": 1000.0})
    assert result is False


def test_save_cycle_summary_no_requests(monkeypatch):
    monkeypatch.setattr(sc, "SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setattr(sc, "SUPABASE_SERVICE_ROLE_KEY", "secret")
    monkeypatch.setattr(sc, "_requests", None)
    result = sc.save_cycle_summary({"total_cycles": 5})
    assert result is False
