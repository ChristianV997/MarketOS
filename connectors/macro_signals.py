"""FRED macro-signals connector.

Fetches key macro indicators from the Federal Reserve Economic Data (FRED)
REST API.  Falls back to static stub values when the API key is absent or
the network is unavailable — ensuring the execution loop always has a
numeric macro context vector.

Environment variables:
  FRED_API_KEY   Your FRED API key (free at https://fred.stlouisfed.org/docs/api/api_key.html)

Signals returned
----------------
  fed_funds_rate   Effective Federal Funds Rate (EFFR)
  cpi_yoy          CPI YoY % change (CPIAUCSL, 12-month delta)
  unemployment     US Unemployment Rate (UNRATE)
  sp500_pe         S&P 500 P/E ratio proxy via CAPE (MULTPL/SHILLER_PE_RATIO_MONTH)
                   Note: FRED does not host Shiller CAPE directly; we use the
                   10-year Treasury yield (DGS10) as a cheap substitute signal.
  treasury_10y     10-Year Treasury Constant Maturity Rate (DGS10)
"""
import datetime
import os

try:
    import requests as _requests
except ImportError:  # pragma: no cover
    _requests = None

FRED_API_KEY = os.getenv("FRED_API_KEY", "")
_BASE = "https://api.stlouisfed.org/fred/series/observations"

# Stub values represent approximate long-run averages (not investment advice)
_FALLBACK: dict[str, float] = {
    "fed_funds_rate": 5.25,
    "cpi_yoy": 3.2,
    "unemployment": 4.0,
    "treasury_10y": 4.5,
    "macro_risk_score": 0.5,  # composite 0-1
}

_SERIES: dict[str, str] = {
    "fed_funds_rate": "EFFR",
    "cpi_yoy": "CPIAUCSL",
    "unemployment": "UNRATE",
    "treasury_10y": "DGS10",
}


def _fetch_observations(series_id: str, start: str, *, limit: int = 5) -> list[dict]:
    """Return raw FRED observations for *series_id* from *start* onward
    (most-recent first), or [] on any error."""
    if not FRED_API_KEY or _requests is None:
        return []
    try:
        resp = _requests.get(
            _BASE,
            params={
                "series_id": series_id,
                "api_key": FRED_API_KEY,
                "file_type": "json",
                "observation_start": start,
                "sort_order": "desc",
                "limit": limit,
            },
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("observations", [])
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        return []


def _fetch_latest(series_id: str) -> float | None:
    """Return the most-recent observation for *series_id* or None on error."""
    now = datetime.datetime.now(datetime.UTC).date()
    # Request last 90 days to ensure we get the most-recent release
    start = (now - datetime.timedelta(days=90)).isoformat()
    for o in _fetch_observations(series_id, start):
        val = o.get("value", ".")
        if val != ".":
            return float(val)
    return None


def _fetch_yoy_pct_change(series_id: str) -> float | None:
    """Return the year-over-year percent change for *series_id*, or None.

    CPIAUCSL (and similarly-shaped FRED series) are raw index levels
    (~310 for CPI, not a percentage) — treating the level itself as a
    already-a-percentage YoY figure silently pinned `_macro_risk`'s
    `cpi_norm` term to its 1.0 ceiling on every real (non-fallback) fetch,
    since (310 - 2.0) / 8.0 clips far above 1.0. This fetches both the
    latest observation and one from ~12 months prior and computes the
    actual percent change.
    """
    now = datetime.datetime.now(datetime.UTC).date()
    latest_obs = _fetch_observations(series_id, (now - datetime.timedelta(days=90)).isoformat())
    latest_val: float | None = None
    for o in latest_obs:
        val = o.get("value", ".")
        if val != ".":
            latest_val = float(val)
            break
    if latest_val is None:
        return None

    # Monthly series can release with a lag, so widen the prior-year
    # window (335-395 days back) rather than requesting a single date.
    prior_start = (now - datetime.timedelta(days=395)).isoformat()
    prior_end_cutoff = now - datetime.timedelta(days=335)
    prior_val: float | None = None
    for o in _fetch_observations(series_id, prior_start, limit=10):
        try:
            obs_date = datetime.date.fromisoformat(o.get("date", ""))
        except ValueError:
            continue
        if obs_date > prior_end_cutoff:
            continue
        val = o.get("value", ".")
        if val != ".":
            prior_val = float(val)
            break
    if prior_val is None or prior_val == 0:
        return None

    return round((latest_val - prior_val) / prior_val * 100.0, 4)


def _macro_risk(signals: dict) -> float:
    """Heuristic composite macro risk score in [0, 1].

    Higher score → more macro risk / tighter environment.
    """
    rate = signals.get("fed_funds_rate", _FALLBACK["fed_funds_rate"])
    cpi = signals.get("cpi_yoy", _FALLBACK["cpi_yoy"])
    ue = signals.get("unemployment", _FALLBACK["unemployment"])

    # Normalise each driver to [0, 1] using soft caps
    rate_norm = min(1.0, max(0.0, rate / 10.0))
    cpi_norm = min(1.0, max(0.0, (cpi - 2.0) / 8.0))  # 2 % = 0, 10 % = 1
    ue_norm = min(1.0, max(0.0, (ue - 3.5) / 6.5))     # 3.5 % = 0, 10 % = 1

    return round((rate_norm + cpi_norm + ue_norm) / 3.0, 4)


def get_macro_signals() -> dict:
    """Return a dict of macro indicator values with a composite risk score.

    Always succeeds — falls back to ``_FALLBACK`` values on any error.
    """
    signals: dict[str, float] = {}

    for key, series_id in _SERIES.items():
        if key == "cpi_yoy":
            # CPIAUCSL is a raw index level, not YoY % — compute the real
            # year-over-year delta instead of passing the level through.
            val = _fetch_yoy_pct_change(series_id)
        else:
            val = _fetch_latest(series_id)
        signals[key] = val if val is not None else _FALLBACK[key]

    signals["macro_risk_score"] = _macro_risk(signals)
    return signals


def is_configured() -> bool:
    """True when a FRED API key is present."""
    return bool(FRED_API_KEY)
