"""Tests for connectors/macro_signals.py"""
from unittest.mock import MagicMock

import connectors.macro_signals as ms


def test_get_macro_signals_no_key(monkeypatch):
    monkeypatch.setattr(ms, "FRED_API_KEY", "")
    signals = ms.get_macro_signals()
    # Should return fallback values
    assert "fed_funds_rate" in signals
    assert "cpi_yoy" in signals
    assert "unemployment" in signals
    assert "treasury_10y" in signals
    assert "macro_risk_score" in signals


def test_fallback_values_are_numeric(monkeypatch):
    monkeypatch.setattr(ms, "FRED_API_KEY", "")
    signals = ms.get_macro_signals()
    for key, val in signals.items():
        assert isinstance(val, float), f"{key} should be float, got {type(val)}"


def test_macro_risk_in_range(monkeypatch):
    monkeypatch.setattr(ms, "FRED_API_KEY", "")
    signals = ms.get_macro_signals()
    risk = signals["macro_risk_score"]
    assert 0.0 <= risk <= 1.0


def test_is_configured_no_key(monkeypatch):
    monkeypatch.setattr(ms, "FRED_API_KEY", "")
    assert ms.is_configured() is False


def test_is_configured_with_key(monkeypatch):
    monkeypatch.setattr(ms, "FRED_API_KEY", "abc123")
    assert ms.is_configured() is True


def test_get_macro_signals_no_requests(monkeypatch):
    monkeypatch.setattr(ms, "FRED_API_KEY", "abc123")
    monkeypatch.setattr(ms, "_requests", None)
    signals = ms.get_macro_signals()
    # Should still return fallback values
    assert "macro_risk_score" in signals
    assert isinstance(signals["macro_risk_score"], float)


def test_macro_risk_high_rate():
    """High interest rates should push macro risk upward."""
    signals = {"fed_funds_rate": 9.0, "cpi_yoy": 8.0, "unemployment": 8.0}
    risk = ms._macro_risk(signals)
    assert risk > 0.5


def test_macro_risk_low_rate():
    """Low rates / low inflation should give low macro risk."""
    signals = {"fed_funds_rate": 0.5, "cpi_yoy": 1.5, "unemployment": 3.5}
    risk = ms._macro_risk(signals)
    assert risk < 0.5


# ── cpi_yoy: real percent change, not a raw index level ───────────────────────

def _fred_response(observations):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"observations": observations}
    return resp


def test_fetch_yoy_pct_change_computes_real_percentage(monkeypatch):
    """CPIAUCSL returns raw index levels (~310), not a YoY percentage —
    previously the level was passed straight through as cpi_yoy, which
    _macro_risk's (cpi - 2.0) / 8.0 normalization clips to 1.0 for any
    real-world index value. This must compute an actual percent change."""
    monkeypatch.setattr(ms, "FRED_API_KEY", "fake-key")

    latest = _fred_response([{"date": "2026-07-01", "value": "312.0"}])
    prior  = _fred_response([{"date": "2025-07-01", "value": "300.0"}])
    mock_get = MagicMock(side_effect=[latest, prior])
    monkeypatch.setattr(ms, "_requests", MagicMock(get=mock_get))

    pct = ms._fetch_yoy_pct_change("CPIAUCSL")
    assert pct == round((312.0 - 300.0) / 300.0 * 100.0, 4)
    assert 0 < pct < 20  # sane real-world CPI YoY range, not a raw index level


def test_fetch_yoy_pct_change_returns_none_without_prior_value(monkeypatch):
    monkeypatch.setattr(ms, "FRED_API_KEY", "fake-key")
    latest = _fred_response([{"date": "2026-07-01", "value": "312.0"}])
    prior  = _fred_response([{"date": "2025-07-01", "value": "."}])
    monkeypatch.setattr(ms, "_requests", MagicMock(get=MagicMock(side_effect=[latest, prior])))
    assert ms._fetch_yoy_pct_change("CPIAUCSL") is None


def test_get_macro_signals_uses_yoy_pct_for_cpi(monkeypatch):
    monkeypatch.setattr(ms, "FRED_API_KEY", "fake-key")
    monkeypatch.setattr(ms, "_fetch_latest", lambda series_id: 5.0)
    monkeypatch.setattr(ms, "_fetch_yoy_pct_change", lambda series_id: 3.1)
    signals = ms.get_macro_signals()
    assert signals["cpi_yoy"] == 3.1
