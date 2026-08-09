"""Compatibility facade for the canonical TikTok integration.

Campaign lifecycle calls delegate to :mod:`backend.integrations.tiktok_ads`.
OAuth and legacy spend-report helpers remain here for existing callers, but
new commerce code must use the backend integration directly.
"""

import os
import datetime

try:
    import requests as _requests
except ImportError:  # pragma: no cover
    _requests = None

ACCESS_TOKEN = os.getenv("TIKTOK_ACCESS_TOKEN")
ADVERTISER_ID = os.getenv("TIKTOK_ADVERTISER_ID")
API_BASE = "https://business-api.tiktok.com/open_api/v1.3"

_FALLBACK_CAMPAIGNS = [
    {"campaign_id": "tt_camp_1", "spend": 35.0},
    {"campaign_id": "tt_camp_2", "spend": 25.0},
]

_FALLBACK_METRICS = {
    "spend": 30.0,
    "clicks": 450,
    "impressions": 15000,
    "conversions": 12,
    "ctr": 0.030,
    "cvr": 0.027,
    "cpc": 0.067,
    "cpa": 2.5,
}


def _headers() -> dict:
    """Return Authorization headers using the configured access token."""
    return {"Access-Token": ACCESS_TOKEN or ""}


def _post(path: str, payload: dict) -> dict:
    """POST to the TikTok Business API; returns parsed JSON or raises."""
    url = f"{API_BASE}{path}"
    resp = _requests.post(url, json=payload, headers=_headers(), timeout=15)
    resp.raise_for_status()
    return resp.json()


def _get(path: str, params: dict) -> dict:
    """GET from the TikTok Business API; returns parsed JSON or raises."""
    url = f"{API_BASE}{path}"
    resp = _requests.get(url, params=params, headers=_headers(), timeout=15)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Token / OAuth helpers
# ---------------------------------------------------------------------------

def exchange_code_for_token(app_id: str, secret: str, auth_code: str) -> dict:
    """Exchange an OAuth authorization code for an access + refresh token pair.

    Falls back to a stub response when credentials are absent or requests
    is unavailable (test / offline environments).
    """
    if not (app_id and secret and auth_code) or _requests is None:
        return {"access_token": "", "refresh_token": "", "advertiser_ids": []}

    try:
        data = _post(
            "/oauth2/access_token/",
            {"app_id": app_id, "secret": secret, "auth_code": auth_code},
        )
        return {
            "access_token": data.get("data", {}).get("access_token", ""),
            "refresh_token": data.get("data", {}).get("refresh_token", ""),
            "advertiser_ids": data.get("data", {}).get("advertiser_ids", []),
        }
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        return {"access_token": "", "refresh_token": "", "advertiser_ids": []}


def refresh_access_token(app_id: str, secret: str, refresh_token: str) -> dict:
    """Refresh an expired access token.

    Falls back to a stub when offline.
    """
    if not (app_id and secret and refresh_token) or _requests is None:
        return {"access_token": "", "refresh_token": refresh_token}

    try:
        data = _post(
            "/oauth2/refresh_token/",
            {"app_id": app_id, "secret": secret, "refresh_token": refresh_token},
        )
        return {
            "access_token": data.get("data", {}).get("access_token", ""),
            "refresh_token": data.get("data", {}).get("refresh_token", refresh_token),
        }
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        return {"access_token": "", "refresh_token": refresh_token}


# ---------------------------------------------------------------------------
# Campaign / Ad Group / Ad management
# ---------------------------------------------------------------------------

def create_campaign(
    name: str,
    objective: str = "CONVERSIONS",
    budget: float = 50.0,
    budget_mode: str = "BUDGET_MODE_DAY",
) -> dict:
    """Create a TikTok campaign and return its ID.

    Falls back to a stub dict when credentials are missing.
    """
    if not (ACCESS_TOKEN and ADVERTISER_ID) or _requests is None:
        return {"campaign_id": "tt_mock_camp_1", "status": "created"}
    from backend.integrations.tiktok_ads import create_campaign as _canonical_create_campaign
    campaign_id = _canonical_create_campaign(name=name, objective=objective, budget=budget)
    return {"campaign_id": campaign_id, "status": "created" if campaign_id else "error"}


def create_ad_group(
    campaign_id: str,
    name: str,
    budget: float = 20.0,
    budget_mode: str = "BUDGET_MODE_DAY",
    bid: float = 5.0,
    placements: list | None = None,
) -> dict:
    """Create an ad group under a campaign and return its ID.

    Falls back to a stub when offline.
    """
    if not (ACCESS_TOKEN and ADVERTISER_ID) or _requests is None:
        return {"adgroup_id": "tt_mock_adgroup_1", "status": "created"}
    from backend.integrations.tiktok_ads import create_ad_group as _canonical_create_ad_group
    adgroup_id = _canonical_create_ad_group(campaign_id, name=name, daily_budget=budget, placements=placements)
    return {"adgroup_id": adgroup_id, "status": "created" if adgroup_id else "error"}


def create_ad(
    adgroup_id: str,
    creative: dict,
) -> dict:
    """Create a single ad under an ad group and return its ID.

    *creative* should contain at least ``headline``, ``body``, and ``cta`` keys.
    Falls back to a stub when offline.
    """
    if not (ACCESS_TOKEN and ADVERTISER_ID) or _requests is None:
        return {"ad_id": "tt_mock_ad_1", "status": "created"}
    from backend.integrations.tiktok_ads import create_ad as _canonical_create_ad
    ad_id = _canonical_create_ad(
        adgroup_id=adgroup_id,
        creative_id=str(creative.get("creative_id") or creative.get("headline") or "creative"),
        name=str(creative.get("headline") or "Ad"),
        hook=str(creative.get("body") or ""),
        angle=str(creative.get("cta") or ""),
    )
    return {"ad_id": ad_id, "status": "created" if ad_id else "error"}


# ---------------------------------------------------------------------------
# Metrics / reporting
# ---------------------------------------------------------------------------

def get_metrics(
    campaign_ids: list | None = None,
    last_n_days: int = 1,
) -> dict:
    """Return detailed performance metrics (spend, clicks, conversions, CTR, CVR).

    Falls back to ``_FALLBACK_METRICS`` when credentials are absent or a
    network error occurs.
    """
    from backend.integrations.tiktok_ads import get_metrics as _canonical_get_metrics
    return _canonical_get_metrics(campaign_ids=campaign_ids, last_n_days=last_n_days)


def get_ad_spend(last_n_minutes: int = 60) -> dict:
    """Return campaign spend from TikTok Ads, falling back to mock data."""
    now = datetime.datetime.now(datetime.UTC)
    since = now - datetime.timedelta(minutes=last_n_minutes)

    campaigns = _FALLBACK_CAMPAIGNS

    if ACCESS_TOKEN and ADVERTISER_ID and _requests is not None:
        try:
            url = f"{API_BASE}/report/integrated/get/"
            headers = {"Access-Token": ACCESS_TOKEN}
            params = {
                "advertiser_id": ADVERTISER_ID,
                "report_type": "BASIC",
                "data_level": "AUCTION_CAMPAIGN",
                "dimensions": '["campaign_id"]',
                "metrics": '["spend"]',
                "start_date": since.date().isoformat(),
                "end_date": now.date().isoformat(),
            }
            resp = _requests.get(url, headers=headers, params=params, timeout=10)
            resp.raise_for_status()
            payload = resp.json()
            rows = payload.get("data", {}).get("list", [])
            parsed = [
                {
                    "campaign_id": row["dimensions"]["campaign_id"],
                    "spend": float(row["metrics"].get("spend", 0)),
                }
                for row in rows
                if row.get("dimensions", {}).get("campaign_id")
            ]
            if parsed:
                campaigns = parsed
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            campaigns = _FALLBACK_CAMPAIGNS

    total_spend = sum(c["spend"] for c in campaigns)
    return {
        "campaigns": campaigns,
        "total_spend": total_spend,
        "since": since.isoformat(),
        "until": now.isoformat(),
    }
