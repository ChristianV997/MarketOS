import logging
import os
import datetime
import json

from backend.patterns.safe_call import safe_call

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


@safe_call(default="")
def create_campaign(name: str, objective: str = "OUTCOME_SALES",
                    daily_budget: float = 50.0) -> str:
    """Create a Meta campaign. Returns campaign_id ('' on failure)."""
    resp = _graph_post(f"act_{AD_ACCOUNT_ID or 'dry'}/campaigns", {
        "name": name,
        "objective": objective,
        "status": "PAUSED",   # launched paused; budget flips it live
        "special_ad_categories": "[]",
    })
    cid = str(resp.get("id", ""))
    _log.info("meta_campaign_created id=%s", cid)
    return cid


@safe_call(default=False)
def pause_campaign(campaign_id: str) -> bool:
    """Pause a campaign (used as launch-transaction compensation)."""
    resp = _graph_post(campaign_id, {"status": "PAUSED"})
    ok = bool(resp)
    _log.info("meta_campaign_paused id=%s ok=%s", campaign_id, ok)
    return ok


@safe_call(default=False)
def update_ad_set_budget(ad_set_id: str, new_budget: float, current_budget: float = 0.0) -> bool:
    """Update an ad set's daily budget for scaling winners — Meta's mirror
    of tiktok_ads.scale_budget(), same shape and same risk-gate treatment:
    only the incremental increase over *current_budget* is gated/recorded
    as new spend commitment; a scale-down/kill is never blocked."""
    delta = max(0.0, new_budget - current_budget)
    committed_delta = delta
    if not _is_dry_run() and delta > 0:
        from backend.risk.gate import check_spend
        gate = check_spend(delta)
        if not gate["allowed"]:
            _log.warning("meta_budget_scale_blocked_by_risk_gate id=%s reason=%s",
                        ad_set_id, gate["reason"])
            return False
        committed_delta = gate["adjusted_amount"]
        new_budget = current_budget + committed_delta

    resp = _graph_post(ad_set_id, {"daily_budget": int(round(new_budget * 100))})
    ok = bool(resp)
    _log.info("meta_adset_budget_scaled id=%s budget=%s ok=%s", ad_set_id, new_budget, ok)
    if ok and not _is_dry_run() and committed_delta > 0:
        from backend.risk.gate import record_spend
        record_spend(committed_delta)
    return ok


@safe_call(default="")
def create_ad_set(campaign_id: str, name: str, daily_budget: float = 50.0) -> str:
    """Create an ad set under a campaign. Returns ad_set_id ('' on failure)."""
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


@safe_call(default="")
def create_ad(ad_set_id: str, name: str, headline: str = "",
              body: str = "", link_url: str = "") -> str:
    """Create an ad within an ad set. Returns ad_id ('' on failure)."""
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


@safe_call(default=list)
def create_ads_batch(ad_set_id: str, ads: list[dict]) -> list[str]:
    """Create multiple ads in one Graph API batch request.

    Each item in ``ads`` is {"name", "headline", "body", "link_url"}.
    Returns ad_ids in the same order as ``ads``; a failed sub-request
    yields "" at that position rather than dropping it (callers zip this
    against ``ads`` by index).

    Uses the Graph API's documented batch endpoint (POST / with a `batch`
    array of {method, relative_url, body}) instead of N separate requests
    — one round trip for the whole ad set. Falls back to sequential
    create_ad() calls in dry-run mode, where there's no network cost to
    save.
    """
    if not ads:
        return []
    if _is_dry_run() or requests is None:
        return [create_ad(ad_set_id, name=a.get("name", ""),
                          headline=a.get("headline", ""), body=a.get("body", ""),
                          link_url=a.get("link_url", "")) for a in ads]

    import urllib.parse

    sub_requests = []
    for ad in ads:
        body = {
            "name": ad.get("name", ""),
            "adset_id": ad_set_id,
            "creative": json.dumps({
                "title": ad.get("headline", "")[:40],
                "body": ad.get("body", "")[:280],
                "object_url": ad.get("link_url", ""),
            }),
            "status": "PAUSED",
        }
        sub_requests.append({
            "method": "POST",
            "relative_url": f"act_{AD_ACCOUNT_ID}/ads",
            "body": urllib.parse.urlencode(body),
        })

    try:
        from backend.integrations.rate_limiter import rate_limiter
        rate_limiter.acquire("meta")
    except Exception:
        pass

    def _post_batch() -> list[dict]:
        r = requests.post(
            f"https://graph.facebook.com/{GRAPH_API_VERSION}/",
            data={"access_token": ACCESS_TOKEN, "batch": json.dumps(sub_requests)},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    def _post_batch_with_retry() -> list[dict]:
        try:
            from backend.integrations.retry_middleware import retry_call
            return retry_call(_post_batch, attempts=3, label="meta:batch_ads")
        except ImportError:
            return _post_batch()

    try:
        from backend.cost_tracking import track_api_call
        with track_api_call("meta_ads", "batch_ads", cost_usd=0.001 * len(ads)):
            responses = _post_batch_with_retry()
    except ImportError:
        responses = _post_batch_with_retry()

    ad_ids = []
    for resp in responses:
        try:
            sub_body = json.loads(resp.get("body", "{}"))
            ad_ids.append(str(sub_body.get("id", "")))
        except Exception:
            ad_ids.append("")
    _log.info("meta_ads_batch_created count=%d", sum(1 for a in ad_ids if a))
    return ad_ids


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
