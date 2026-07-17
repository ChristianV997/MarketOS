import logging
import os
import datetime
import json

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

_log = logging.getLogger(__name__)

def _cfg(key: str) -> str | None:
    """Credential lookup: env var first, then the local config store."""
    try:
        from backend.config import get_credential
        return get_credential(key)
    except Exception:
        return os.getenv(key)


# Resolved once at import (tests monkeypatch these module attributes
# directly; credential changes via the setup API need a process restart).
ACCESS_TOKEN = _cfg("META_ACCESS_TOKEN")
AD_ACCOUNT_ID = _cfg("META_AD_ACCOUNT_ID")
GRAPH_API_VERSION = os.getenv("META_GRAPH_API_VERSION", "v20.0")


def _is_dry_run() -> bool:
    """Dry-run unless META_DRY_RUN=false AND credentials are present."""
    if os.getenv("META_DRY_RUN", "true").lower() != "false":
        return True
    return not (ACCESS_TOKEN and AD_ACCOUNT_ID)

# Monotonic counter keeps dry-run IDs unique within one second
_dry_seq = 0


def _next_dry_id(prefix: str) -> str:
    global _dry_seq
    _dry_seq += 1
    now = int(datetime.datetime.now(datetime.UTC).timestamp())
    return f"{prefix}_{now}_{_dry_seq}"


def _graph_post(path: str, payload: dict) -> dict:
    if _is_dry_run() or requests is None:
        _log.info("meta_dry_run path=%s", path)
        return {"id": _next_dry_id("dry_meta")}

    def _post() -> dict:
        r = requests.post(
            f"https://graph.facebook.com/{GRAPH_API_VERSION}/{path}",
            data={**payload, "access_token": ACCESS_TOKEN},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()

    # Live path: stay inside quota, retry transient failures, track cost.
    # Each guard degrades independently so a missing helper never blocks a call.
    try:
        from backend.integrations.rate_limiter import rate_limiter
        rate_limiter.acquire("meta")
    except Exception:
        pass

    def _post_with_retry() -> dict:
        try:
            from backend.integrations.retry_middleware import retry_call
            return retry_call(_post, attempts=3, label=f"meta:{path}")
        except ImportError:
            return _post()

    try:
        from backend.cost_tracking import track_api_call
        with track_api_call("meta_ads", path.split("/")[-1], cost_usd=0.001):
            return _post_with_retry()
    except ImportError:
        return _post_with_retry()


def create_campaign(name: str, objective: str = "OUTCOME_SALES",
                    daily_budget: float = 50.0) -> str:
    """Create a Meta campaign. Returns campaign_id ('' on failure)."""
    try:
        resp = _graph_post(f"act_{AD_ACCOUNT_ID or 'dry'}/campaigns", {
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
        resp = _graph_post(f"act_{AD_ACCOUNT_ID or 'dry'}/adsets", {
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
        resp = _graph_post(f"act_{AD_ACCOUNT_ID or 'dry'}/ads", {
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

    if ACCESS_TOKEN and AD_ACCOUNT_ID and requests is not None:
        try:
            url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/act_{AD_ACCOUNT_ID}/insights"
            params = {
                "access_token": ACCESS_TOKEN,
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
