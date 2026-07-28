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

    monkeypatch.setattr(mod._stripe.Charge, "list", lambda *a, **kw: fixture_payload)

    result = mod.get_revenue(last_n_minutes=60)
    assert result["total_revenue"] == 75.0  # (5000+2500) cents -> $75
    assert len(result["charges"]) == 2


def test_get_revenue_falls_back_to_mock_on_api_failure(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fake")
    import connectors.stripe_connector as mod
    importlib.reload(mod)

    def _raise(*a, **kw):
        raise Exception("network error")

    monkeypatch.setattr(mod._stripe.Charge, "list", _raise)

    result = mod.get_revenue(last_n_minutes=60)
    assert result["total_revenue"] == 180.0  # falls back to mock charges


def test_get_revenue_uses_real_stripe_objects_not_just_dicts(monkeypatch):
    """Regression guard: a real stripe.ListObject/stripe.Charge (unlike a
    plain dict) raises AttributeError on `.get(...)` — .get is routed
    through __getattr__ to a key lookup. Build the fixture from real SDK
    objects (bracket assignment only) so this actually exercises that
    behavior rather than a dict mock that happens to support .get()."""
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fake")
    import connectors.stripe_connector as mod
    importlib.reload(mod)

    charge = mod._stripe.Charge()
    charge["id"] = "ch_real_1"
    charge["amount"] = 5000
    charge["currency"] = "usd"
    charge["status"] = "succeeded"

    listing = mod._stripe.ListObject()
    listing["data"] = [charge]

    monkeypatch.setattr(mod._stripe.Charge, "list", lambda *a, **kw: listing)

    result = mod.get_revenue(last_n_minutes=60)
    assert result["source"] == "live"
    assert result["total_revenue"] == 50.0
    assert result["charges"] == [
        {"id": "ch_real_1", "amount": 5000, "currency": "usd", "status": "succeeded"}
    ]


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

    monkeypatch.setattr(mod._stripe.Charge, "list", lambda *a, **kw: fixture_payload)

    result = mod.get_revenue(last_n_minutes=60)
    assert result["total_revenue"] == 50.0  # only the succeeded charge counts
