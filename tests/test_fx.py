"""Tests for backend.core.fx — explicit currency handling for capital figures."""
import pytest


def test_default_currency_is_usd(monkeypatch):
    monkeypatch.delenv("CAPITAL_CURRENCY", raising=False)
    from backend.core.fx import capital_currency
    assert capital_currency() == "USD"


def test_to_usd_is_identity_for_usd():
    from backend.core.fx import to_usd
    assert to_usd(1000.0, "USD") == 1000.0


def test_to_usd_converts_mxn():
    from backend.core.fx import to_usd
    assert to_usd(5000.0, "MXN") == round(5000.0 / 18.50, 2)


def test_to_usd_uses_env_currency_when_unspecified(monkeypatch):
    monkeypatch.setenv("CAPITAL_CURRENCY", "MXN")
    from backend.core.fx import to_usd
    assert to_usd(5000.0) == round(5000.0 / 18.50, 2)


def test_unknown_currency_raises():
    from backend.core.fx import to_usd
    with pytest.raises(ValueError):
        to_usd(100.0, "XYZ")


def test_default_capital_unaffected_when_unset(monkeypatch):
    monkeypatch.delenv("CAPITAL_CURRENCY", raising=False)
    monkeypatch.delenv("INITIAL_CAPITAL", raising=False)
    import importlib
    import backend.core.state as state_mod
    importlib.reload(state_mod)
    assert state_mod.DEFAULT_CAPITAL == 1000.0


def test_default_capital_converts_from_mxn(monkeypatch):
    monkeypatch.setenv("CAPITAL_CURRENCY", "MXN")
    monkeypatch.setenv("INITIAL_CAPITAL", "5000")
    import importlib
    import backend.core.state as state_mod
    importlib.reload(state_mod)
    try:
        assert state_mod.DEFAULT_CAPITAL == round(5000 / 18.50, 2)
    finally:
        monkeypatch.delenv("CAPITAL_CURRENCY", raising=False)
        monkeypatch.delenv("INITIAL_CAPITAL", raising=False)
        importlib.reload(state_mod)  # restore module-level default for later tests
