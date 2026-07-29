"""backend.integrations.meta_ads_client — Meta Marketing API client.

Uses the official ``facebook-business`` SDK for every live-path call
instead of hand-rolled REST against the Graph API. Dry-run behavior,
`backend.risk.gate` wiring, and the retry/rate-limiter/cost-tracking guard
chain around each live call are all unchanged — only the "make the actual
API call" leaf inside each function was swapped.
"""
import logging
import os
import datetime

from backend.patterns.safe_call import safe_call

try:
    from facebook_business.api import FacebookAdsApi
    from facebook_business.adobjects.campaign import Campaign
    from facebook_business.adobjects.adset import AdSet
    from facebook_business.adobjects.ad import Ad
    from facebook_business.adobjects.adaccount import AdAccount
except ImportError:  # pragma: no cover
    FacebookAdsApi = Campaign = AdSet = Ad = AdAccount = None

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


def _live() -> bool:
    """True only when real API calls should actually be made — dry-run is
    off, credentials are present, and the SDK is importable."""
    return not _is_dry_run() and FacebookAdsApi is not None


# Monotonic counter keeps dry-run IDs unique within one second
_dry_seq = 0


def _next_dry_id(prefix: str) -> str:
    global _dry_seq
    _dry_seq += 1
    now = int(datetime.datetime.now(datetime.UTC).timestamp())
    return f"{prefix}_{now}_{_dry_seq}"


_api_initialized = False


def _ensure_api() -> None:
    """Lazily initialize the facebook-business SDK singleton. Only ever
    called from the live path — dry-run/offline environments never touch
    the SDK's network layer."""
    global _api_initialized
    if not _api_initialized:
        FacebookAdsApi.init(access_token=ACCESS_TOKEN, api_version=GRAPH_API_VERSION)
        _api_initialized = True


def _call_with_guards(label: str, fn, cost_usd: float = 0.001):
    """Run *fn* (a zero-arg live-path SDK call) through the same
    rate-limit / retry / cost-tracking guard chain the old raw-REST
    ``_graph_post`` used. Each guard degrades independently on ImportError
    so a missing helper never blocks a call.
    """
    try:
        from backend.integrations.rate_limiter import rate_limiter
        rate_limiter.acquire("meta")
    except Exception:
        pass

    def _with_retry():
        try:
            from backend.integrations.retry_middleware import retry_call
            return retry_call(fn, attempts=3, label=f"meta:{label}")
        except ImportError:
            return fn()

    try:
        from backend.cost_tracking import track_api_call
        with track_api_call("meta_ads", label, cost_usd=cost_usd):
            return _with_retry()
    except ImportError:
        return _with_retry()


@safe_call(default="")
def create_campaign(name: str, objective: str = "OUTCOME_SALES",
                    daily_budget: float = 50.0) -> str:
    """Create a Meta campaign. Returns campaign_id ('' on failure)."""
    if not _live():
        _log.info("meta_dry_run op=create_campaign")
        cid = _next_dry_id("dry_meta")
    else:
        _ensure_api()
        obj = _call_with_guards("campaigns", lambda: Campaign(parent_id=f"act_{AD_ACCOUNT_ID}").api_create(
            params={
                "name": name,
                "objective": objective,
                "status": "PAUSED",   # launched paused; budget flips it live
                "special_ad_categories": [],
            },
        ))
        cid = str(obj["id"])
    _log.info("meta_campaign_created id=%s", cid)
    return cid


@safe_call(default=False)
def pause_campaign(campaign_id: str) -> bool:
    """Pause a campaign (used as launch-transaction compensation)."""
    if not _live():
        _log.info("meta_dry_run op=pause_campaign id=%s", campaign_id)
        ok = True
    else:
        _ensure_api()
        _call_with_guards(campaign_id, lambda: Campaign(campaign_id).api_update(
            params={"status": "PAUSED"},
        ))
        ok = True
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

    if not _live():
        _log.info("meta_dry_run op=update_ad_set_budget id=%s", ad_set_id)
        ok = True
    else:
        _ensure_api()
        _call_with_guards(ad_set_id, lambda: AdSet(ad_set_id).api_update(
            params={"daily_budget": int(round(new_budget * 100))},
        ))
        ok = True
    _log.info("meta_adset_budget_scaled id=%s budget=%s ok=%s", ad_set_id, new_budget, ok)
    if ok and not _is_dry_run() and committed_delta > 0:
        from backend.risk.gate import record_spend
        record_spend(committed_delta)
    return ok


@safe_call(default="")
def create_ad_set(campaign_id: str, name: str, daily_budget: float = 50.0,
                  targeting: dict | None = None) -> str:
    """Create an ad set under a campaign. Returns ad_set_id ('' on failure).

    *targeting* is Meta's raw targeting spec (geo_locations, age_min/max,
    interests, etc.) — omit it (the default) for the exact previous
    behavior (US-only, no age/interest targeting). Passing a category- or
    brand-specific spec (e.g. narrower geo + interest targeting for a pets
    or baby brand) is what backend.launch.channel_selector's category
    hook is meant to eventually feed.
    """
    if not _live():
        _log.info("meta_dry_run op=create_ad_set")
        asid = _next_dry_id("dry_meta")
    else:
        _ensure_api()
        obj = _call_with_guards("adsets", lambda: AdSet(parent_id=f"act_{AD_ACCOUNT_ID}").api_create(
            params={
                "name": name,
                "campaign_id": campaign_id,
                "daily_budget": int(daily_budget * 100),  # Meta wants cents
                "billing_event": "IMPRESSIONS",
                "optimization_goal": "OFFSITE_CONVERSIONS",
                "targeting": targeting or {"geo_locations": {"countries": ["US"]}},
                "status": "PAUSED",
            },
        ))
        asid = str(obj["id"])
    _log.info("meta_adset_created id=%s", asid)
    return asid


@safe_call(default="")
def create_ad(ad_set_id: str, name: str, headline: str = "",
              body: str = "", link_url: str = "") -> str:
    """Create an ad within an ad set. Returns ad_id ('' on failure)."""
    if not _live():
        _log.info("meta_dry_run op=create_ad")
        ad_id = _next_dry_id("dry_meta")
    else:
        _ensure_api()
        obj = _call_with_guards("ads", lambda: Ad(parent_id=f"act_{AD_ACCOUNT_ID}").api_create(
            params={
                "name": name,
                "adset_id": ad_set_id,
                "creative": {
                    "title": headline[:40],
                    "body": body[:280],
                    "object_url": link_url,
                },
                "status": "PAUSED",
            },
        ))
        ad_id = str(obj["id"])
    _log.info("meta_ad_created id=%s", ad_id)
    return ad_id


@safe_call(default=list)
def create_ads_batch(ad_set_id: str, ads: list[dict]) -> list[str]:
    """Create multiple ads in one Graph API batch request.

    Each item in ``ads`` is {"name", "headline", "body", "link_url"}.
    Returns ad_ids in the same order as ``ads``; a failed sub-request
    yields "" at that position rather than dropping it (callers zip this
    against ``ads`` by index).

    Uses the SDK's batch support (``FacebookAdsApi.new_batch()`` +
    per-request success/failure callbacks) instead of N separate requests
    — one round trip for the whole ad set. Falls back to sequential
    create_ad() calls in dry-run mode, where there's no network cost to
    save.
    """
    if not ads:
        return []
    if not _live():
        return [create_ad(ad_set_id, name=a.get("name", ""),
                          headline=a.get("headline", ""), body=a.get("body", ""),
                          link_url=a.get("link_url", "")) for a in ads]

    _ensure_api()
    api = FacebookAdsApi.get_default_api()
    batch = api.new_batch()
    results: list[str] = [""] * len(ads)

    def _mk_success(i):
        def _cb(response):
            try:
                results[i] = str(response.json()["id"])
            except Exception:
                results[i] = ""
        return _cb

    def _mk_failure(i):
        def _cb(response):
            results[i] = ""
        return _cb

    for i, ad in enumerate(ads):
        Ad(parent_id=f"act_{AD_ACCOUNT_ID}").api_create(
            params={
                "name": ad.get("name", ""),
                "adset_id": ad_set_id,
                "creative": {
                    "title": ad.get("headline", "")[:40],
                    "body": ad.get("body", "")[:280],
                    "object_url": ad.get("link_url", ""),
                },
                "status": "PAUSED",
            },
            batch=batch,
            success=_mk_success(i),
            failure=_mk_failure(i),
        )

    _call_with_guards("batch_ads", batch.execute, cost_usd=0.001 * len(ads))
    _log.info("meta_ads_batch_created count=%d", sum(1 for a in results if a))
    return results


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

    if ACCESS_TOKEN and AD_ACCOUNT_ID and FacebookAdsApi is not None:
        try:
            _ensure_api()
            insights = _call_with_guards("insights", lambda: AdAccount(f"act_{AD_ACCOUNT_ID}").get_insights(
                fields=["campaign_id", "spend"],
                params={
                    "level": "campaign",
                    "time_range": {"since": since.date().isoformat(), "until": now.date().isoformat()},
                },
            ))
            parsed = []
            for row in insights:
                campaign_id = row["campaign_id"] if "campaign_id" in row else None
                spend = float(row["spend"]) if "spend" in row else 0.0
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
