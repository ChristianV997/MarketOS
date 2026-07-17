import logging
import os
import datetime
import json

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

_log = logging.getLogger(__name__)

# Use config system for credentials (falls back to env vars)
try:
    from backend.config import get_credential, is_dry_run
    _ACCESS_TOKEN_FN = lambda: get_credential("META_ACCESS_TOKEN")
    _AD_ACCOUNT_ID_FN = lambda: get_credential("META_AD_ACCOUNT_ID")
    _IS_DRY_RUN_FN = lambda: is_dry_run("meta")
except ImportError:
    # Fallback if config module not available (e.g., in tests)
    _ACCESS_TOKEN_FN = lambda: os.getenv("META_ACCESS_TOKEN")
    _AD_ACCOUNT_ID_FN = lambda: os.getenv("META_AD_ACCOUNT_ID")
    _IS_DRY_RUN_FN = lambda: os.getenv("META_DRY_RUN", "true").lower() != "false"

GRAPH_API_VERSION = os.getenv("META_GRAPH_API_VERSION", "v20.0")

# Monotonic counter keeps dry-run IDs unique within one second
_dry_seq = 0


def _next_dry_id(prefix: str) -> str:
    global _dry_seq
    _dry_seq += 1
    now = int(datetime.datetime.now(datetime.UTC).timestamp())
    return f"{prefix}_{now}_{_dry_seq}"


def _graph_post(path: str, payload: dict) -> dict:
    access_token = _ACCESS_TOKEN_FN()
    ad_account_id = _AD_ACCOUNT_ID_FN()
    is_dry = _IS_DRY_RUN_FN()

    if is_dry or not (access_token and ad_account_id and requests is not None):
        _log.info("meta_dry_run path=%s", path)
        return {"id": _next_dry_id("dry_meta")}

    # Track cost: Meta Graph API calls typically cost ~$0.001 each for most operations
    try:
        from backend.cost_tracking import track_api_call
        with track_api_call("meta_ads", path.split("/")[-1], cost_usd=0.001):
            r = requests.post(
                f"https://graph.facebook.com/{GRAPH_API_VERSION}/{path}",
                data={**payload, "access_token": access_token},
                timeout=15,
            )
            r.raise_for_status()
            return r.json()
    except ImportError:
        # Fallback if cost_tracking not available
        r = requests.post(
            f"https://graph.facebook.com/{GRAPH_API_VERSION}/{path}",
            data={**payload, "access_token": access_token},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()


def create_campaign(name: str, objective: str = "OUTCOME_SALES",
                    daily_budget: float = 50.0) -> str:
    """Create a Meta campaign. Returns campaign_id ('' on failure)."""
    try:
        ad_account_id = _AD_ACCOUNT_ID_FN()
        resp = _graph_post(f"act_{ad_account_id or 'dry'}/campaigns", {
            "name": name,
            "objective": objective,
            "status": "PAUSED",   # launched paused; budget flips it live
            "special_ad_categories": "[]",
        })
        cid = str(resp.get("id", ""))
        _log.info("meta_campaign_created id=%s", cid)
        return cid
    except Exception:
        _log.exception("meta create_campaign failed")
        return ""


def create_ad_set(campaign_id: str, name: str, daily_budget: float = 50.0) -> str:
    """Create an ad set under a campaign. Returns ad_set_id ('' on failure)."""
    try:
        ad_account_id = _AD_ACCOUNT_ID_FN()
        resp = _graph_post(f"act_{ad_account_id or 'dry'}/adsets", {
            "name": name,
            "campaign_id": campaign_id,
            "daily_budget": int(daily_budget * 100),  # Meta wants cents
            "billing_event": "IMPRESSIONS",
            "optimization_goal": "OFFSITE_CONVERSIONS",
            "targeting": json.dumps({"geo_locations": {"countries": ["US"]}}),
            "status": "PAUSED",
        })
        asid = str(resp.get("id", ""))
        _log.info("meta_adset_created id=%s", asid)
        return asid
    except Exception:
        _log.exception("meta create_ad_set failed")
        return ""


def create_ad(ad_set_id: str, name: str, headline: str = "",
              body: str = "", link_url: str = "") -> str:
    """Create an ad within an ad set. Returns ad_id ('' on failure)."""
    try:
        ad_account_id = _AD_ACCOUNT_ID_FN()
        resp = _graph_post(f"act_{ad_account_id or 'dry'}/ads", {
            "name": name,
            "adset_id": ad_set_id,
            "creative": json.dumps({
                "title": headline[:40],
                "body": body[:280],
                "object_url": link_url,
            }),
            "status": "PAUSED",
        })
        ad_id = str(resp.get("id", ""))
        _log.info("meta_ad_created id=%s", ad_id)
        return ad_id
    except Exception:
        _log.exception("meta create_ad failed")
        return ""


def get_ad_spend(last_n_minutes=60):
    now = datetime.datetime.now(datetime.UTC)
    since = now - datetime.timedelta(minutes=last_n_minutes)

    # fallback if credentials are missing or request fails
    fallback_campaigns = [
        {"campaign_id": "camp_1", "spend": 50.0},
        {"campaign_id": "camp_2", "spend": 40.0},
        {"campaign_id": "camp_3", "spend": 30.0},
    ]
    campaigns = fallback_campaigns

    access_token = _ACCESS_TOKEN_FN()
    ad_account_id = _AD_ACCOUNT_ID_FN()

    if access_token and ad_account_id and requests is not None:
        try:
            url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/act_{ad_account_id}/insights"
            params = {
                "access_token": access_token,
                "level": "campaign",
                "fields": "campaign_id,spend",
                "time_range": json.dumps(
                    {"since": since.date().isoformat(), "until": now.date().isoformat()}
                ),
            }
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data", [])
            parsed = []
            for row in data:
                campaign_id = row.get("campaign_id")
                spend = float(row.get("spend", 0.0))
                if campaign_id:
                    parsed.append({"campaign_id": campaign_id, "spend": spend})
            if parsed:
                campaigns = parsed
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            campaigns = fallback_campaigns

    total_spend = sum(c["spend"] for c in campaigns)

    return {
        "campaigns": campaigns,
        "total_spend": total_spend,
        "since": since.isoformat(),
        "until": now.isoformat(),
    }
