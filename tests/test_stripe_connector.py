"""Tests for connectors.stripe_connector — Stripe revenue ground-truth source."""
import importlib

import pytest


@pytest.fixture(autouse=True)
def _reload_module(monkeypatch):
    """Ensure STRIPE_SECRET_KEY module-level constant reflects the current env
    for each test (it's read once at import time)."""
    import connectors.stripe_connector as mod
    yield mod
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    importlib.reload(mod)


def test_get_revenue_returns_mock_when_no_key(monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    import connectors.stripe_connector as mod
    importlib.reload(mod)

    result = mod.get_revenue(last_n_minutes=60)
    assert result["total_revenue"] == 180.0  # (10000 + 8000) cents -> $180
    assert len(result["charges"]) == 2
    assert "since" in result and "until" in result


def test_get_revenue_uses_real_api_when_key_set(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fake")
    import connectors.stripe_connector as mod
    importlib.reload(mod)

    fixture_payload = {
        "data": [
            {"id": "ch_real_1", "amount": 5000, "currency": "usd", "status": "succeeded"},
            {"id": "ch_real_2", "amount": 2500, "currency": "usd", "status": "succeeded"},
        ]
    }

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return fixture_payload

    monkeypatch.setattr(mod._requests, "get", lambda *a, **kw: FakeResponse())

    result = mod.get_revenue(last_n_minutes=60)
    assert result["total_revenue"] == 75.0  # (5000+2500) cents -> $75
    assert len(result["charges"]) == 2


def test_get_revenue_falls_back_to_mock_on_api_failure(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fake")
    import connectors.stripe_connector as mod
    importlib.reload(mod)

    def _raise(*a, **kw):
        raise Exception("network error")

    monkeypatch.setattr(mod._requests, "get", _raise)

    result = mod.get_revenue(last_n_minutes=60)
    assert result["total_revenue"] == 180.0  # falls back to mock charges


def test_get_revenue_ignores_non_succeeded_charges(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fake")
    import connectors.stripe_connector as mod
    importlib.reload(mod)

    fixture_payload = {
        "data": [
            {"id": "ch_1", "amount": 5000, "currency": "usd", "status": "succeeded"},
            {"id": "ch_2", "amount": 5000, "currency": "usd", "status": "failed"},
        ]
    }

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return fixture_payload

    monkeypatch.setattr(mod._requests, "get", lambda *a, **kw: FakeResponse())

    result = mod.get_revenue(last_n_minutes=60)
    assert result["total_revenue"] == 50.0  # only the succeeded charge counts
