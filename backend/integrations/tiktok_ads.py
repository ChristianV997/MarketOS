"""backend.integrations.tiktok_ads — TikTok Marketing API v1.3 client.

All calls are no-ops when TIKTOK_DRY_RUN=true (default) or when credentials
are absent. This ensures the module is always safe to import and test without
live credentials.

The single TikTok integration surface — creative upload used to live in a
separate, disjoint pair of modules (core/connectors/tiktok_creatives.py +
tiktok_ads_variants.py) with no shared client, no dry-run gating, and no
production caller (only their own tests exercised them). Merged here as
upload_creative()/create_ads_from_files() so creative upload shares this
module's dry-run/risk-gate conventions.

Production activation: set TIKTOK_DRY_RUN=false and supply:
  TIKTOK_ACCESS_TOKEN, TIKTOK_ADVERTISER_ID, TIKTOK_APP_ID
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

from backend.patterns.safe_call import safe_call

_log = logging.getLogger(__name__)

_BASE   = "https://business-api.tiktok.com/open_api/v1.3"
_DRY_RUN = os.getenv("TIKTOK_DRY_RUN", "true").lower() != "false"
_BUDGET_DAILY = float(os.getenv("TIKTOK_BUDGET_DAILY", "50"))

# Consecutive-win threshold before budget scale-up
_SCALE_WIN_STREAK = int(os.getenv("TIKTOK_SCALE_WIN_STREAK", "3"))
_SCALE_MULTIPLIER = float(os.getenv("TIKTOK_SCALE_MULTIPLIER", "1.5"))
# Kill if spend > budget * X and ROAS < Y
_KILL_SPEND_RATIO = float(os.getenv("TIKTOK_KILL_SPEND_RATIO", "1.2"))
_KILL_ROAS_FLOOR  = float(os.getenv("TIKTOK_KILL_ROAS_FLOOR", "0.8"))

# In-process ROAS streak tracker: {campaign_id → [float, ...]}
_roas_streaks: dict[str, list[float]] = {}

# Monotonic counter for dry-run IDs. A bare int(time.time()) collides for any
# two campaigns launched in the same second, which makes distinct launches
# share a campaign_id and silently overwrite each other in the orchestrator's
# _campaign_artifacts attribution map. The counter guarantees uniqueness.
_dry_seq = 0


def _next_dry_id(prefix: str = "dry") -> str:
    global _dry_seq
    _dry_seq += 1
    return f"{prefix}_{int(time.time())}_{_dry_seq}"


def is_configured() -> bool:
    return bool(os.getenv("TIKTOK_ACCESS_TOKEN") and os.getenv("TIKTOK_ADVERTISER_ID"))


def _headers() -> dict[str, str]:
    return {
        "Access-Token": os.environ["TIKTOK_ACCESS_TOKEN"],
        "Content-Type": "application/json",
    }


def _post(path: str, payload: dict) -> dict:
    if _DRY_RUN:
        _log.info("tiktok_dry_run path=%s payload=%s", path, payload)
        return {"code": 0, "message": "OK", "data": {"campaign_id": _next_dry_id()}}
    import requests
    r = requests.post(f"{_BASE}{path}", headers=_headers(), json=payload, timeout=15)
    r.raise_for_status()
    return r.json()


def _get(path: str, params: dict | None = None) -> dict:
    if _DRY_RUN:
        _log.info("tiktok_dry_run GET path=%s params=%s", path, params)
        return {"code": 0, "message": "OK", "data": {"list": []}}
    import requests
    r = requests.get(f"{_BASE}{path}", headers=_headers(), params=params or {}, timeout=15)
    r.raise_for_status()
    return r.json()


# ── campaign lifecycle ─────────────────────────────────────────────────────────

@safe_call(default="")
def create_campaign(
    name: str,
    objective: str = "CONVERSIONS",
    budget: float | None = None,
) -> str:
    """Create a campaign. Returns campaign_id."""
    resp = _post("/campaign/create/", {
        "advertiser_id": os.getenv("TIKTOK_ADVERTISER_ID", ""),
        "campaign_name": name,
        "objective_type": objective,
        "budget_mode": "BUDGET_MODE_TOTAL",
        "budget": budget or _BUDGET_DAILY,
    })
    cid = resp.get("data", {}).get("campaign_id", f"dry_{name}")
    _log.info("tiktok_campaign_created id=%s", cid)
    return str(cid)


@safe_call(default="")
def create_ad_group(
    campaign_id: str,
    name: str,
    daily_budget: float | None = None,
    placements: list[str] | None = None,
    targeting: dict | None = None,
) -> str:
    """Create an ad group under a campaign. Returns adgroup_id.

    *targeting* merges TikTok's real targeting fields (e.g.
    age_groups, gender, interest_category_ids, location_ids) into the
    payload — omit it (the default) for the exact previous behavior
    (TikTok's own defaults, no explicit targeting).
    """
    payload = {
        "advertiser_id": os.getenv("TIKTOK_ADVERTISER_ID", ""),
        "campaign_id": campaign_id,
        "adgroup_name": name,
        "placement_type": "PLACEMENT_TYPE_NORMAL",
        "placements": placements or ["PLACEMENT_TIKTOK"],
        "budget_mode": "BUDGET_MODE_DAY",
        "budget": daily_budget or _BUDGET_DAILY,
        "schedule_type": "SCHEDULE_FROM_NOW",
        "optimization_goal": "CONVERT",
        "bid_type": "BID_TYPE_NO_BID",
    }
    if targeting:
        payload.update(targeting)
    resp = _post("/adgroup/create/", payload)
    agid = resp.get("data", {}).get("adgroup_id", f"dry_ag_{name}")
    _log.info("tiktok_adgroup_created id=%s", agid)
    return str(agid)


@safe_call(default="")
def create_ad(
    adgroup_id: str,
    creative_id: str,
    name: str,
    hook: str = "",
    angle: str = "",
) -> str:
    """Create an ad within an ad group. Returns ad_id."""
    resp = _post("/ad/create/", {
        "advertiser_id": os.getenv("TIKTOK_ADVERTISER_ID", ""),
        "adgroup_id": adgroup_id,
        "ad_name": name,
        "creatives": [{
            "creative_id": creative_id,
            "ad_text": f"{hook} {angle}".strip()[:100],
        }],
    })
    ad_id = resp.get("data", {}).get("ad_id", f"dry_ad_{name}")
    _log.info("tiktok_ad_created id=%s", ad_id)
    return str(ad_id)


@safe_call(default=list)
def create_ads_batch(adgroup_id: str, ads: list[dict]) -> list[str]:
    """Create multiple ads concurrently for one ad group.

    Each item in ``ads`` is {"creative_id", "name", "hook", "angle"}.
    Returns ad_ids in the same order as ``ads``.

    TikTok's Marketing API doesn't expose a documented bulk ad-create
    endpoint the way Meta's Graph API batch protocol does, so this
    parallelizes the existing single-ad create_ad() calls with a thread
    pool instead of guessing at an unverified bulk endpoint shape — the
    same approach already used for supplier quoting
    (backend/validation/suppliers.py:quote_all). Each create_ad() call is
    independently safe_call-wrapped, so one failing ad returns "" at its
    position without affecting the others.
    """
    if not ads:
        return []
    from concurrent.futures import ThreadPoolExecutor

    def _create(ad: dict) -> str:
        return create_ad(
            adgroup_id=adgroup_id,
            creative_id=ad.get("creative_id", ""),
            name=ad.get("name", ""),
            hook=ad.get("hook", ""),
            angle=ad.get("angle", ""),
        )

    with ThreadPoolExecutor(max_workers=min(len(ads), 5)) as pool:
        return list(pool.map(_create, ads))


@safe_call(default=False)
def pause_campaign(campaign_id: str) -> bool:
    """Pause a campaign (kill-switch)."""
    _post("/campaign/status/update/", {
        "advertiser_id": os.getenv("TIKTOK_ADVERTISER_ID", ""),
        "campaign_ids": [campaign_id],
        "opt_status": "DISABLE",
    })
    _log.info("tiktok_campaign_paused id=%s", campaign_id)
    return True


@safe_call(default=False)
def scale_budget(campaign_id: str, new_budget: float, current_budget: float = 0.0) -> bool:
    """Update campaign daily budget for scaling winners.

    Real (non-dry-run) budget increases pass through the risk gate first —
    a scale-down/kill (new_budget <= current_budget) never gets blocked
    since it reduces spend, not increases it. Only the incremental
    increase over *current_budget* is gated/recorded as new spend commitment
    (not the full new_budget every call, which would overcount cumulative
    spend across repeated scale-ups of the same campaign); when the caller
    doesn't know the prior budget, current_budget defaults to 0 — the
    conservative choice, since it treats the full new_budget as newly
    committed rather than under-counting.
    """
    delta = max(0.0, new_budget - current_budget)
    committed_delta = delta
    if not _DRY_RUN and delta > 0:
        from backend.risk.gate import check_spend
        gate = check_spend(delta)
        if not gate["allowed"]:
            _log.warning("budget_scale_blocked_by_risk_gate id=%s reason=%s",
                        campaign_id, gate["reason"])
            return False
        committed_delta = gate["adjusted_amount"]
        new_budget = current_budget + committed_delta

    _post("/campaign/update/", {
        "advertiser_id": os.getenv("TIKTOK_ADVERTISER_ID", ""),
        "campaign_id": campaign_id,
        "budget": round(new_budget, 2),
    })
    _log.info("tiktok_budget_scaled id=%s budget=%s", campaign_id, new_budget)
    if not _DRY_RUN and committed_delta > 0:
        from backend.risk.gate import record_spend
        record_spend(committed_delta)
    return True


@safe_call(default=dict)
def upload_creative(file_path: str) -> dict:
    """Upload a video file as a TikTok creative. Returns the raw API response
    (or a dry-run/fallback stub with a synthetic ``video_id``).
    """
    if _DRY_RUN:
        _log.info("tiktok_dry_run upload_creative file_path=%s", file_path)
        return {"data": {"video_id": _next_dry_id("vid")}}

    if not is_configured() or not os.path.exists(file_path):
        return {"data": {"video_id": _next_dry_id("vid")}}

    import requests
    url = f"{_BASE}/file/video/ad/upload/"
    with open(file_path, "rb") as fh:
        files = {"video_file": fh}
        data = {"advertiser_id": os.getenv("TIKTOK_ADVERTISER_ID", "")}
        r = requests.post(url, headers={"Access-Token": os.environ["TIKTOK_ACCESS_TOKEN"]},
                          files=files, data=data, timeout=60)
        r.raise_for_status()
        return r.json()


@safe_call(default=list)
def create_ads_from_files(adgroup_id: str, assets: list[dict]) -> list[dict]:
    """Upload each asset's video file and create an ad from it.

    Each item in ``assets`` is {"file_path", "name"} (optionally "hook",
    "angle"). Returns a list of {"campaign_id"/"adgroup_id", "creative_name",
    "video_id", "ad_id"} dicts, one per asset, in order.
    """
    results = []
    for asset in assets:
        video = upload_creative(asset["file_path"])
        video_id = video.get("data", {}).get("video_id", "")
        ad_id = create_ad(
            adgroup_id=adgroup_id,
            creative_id=video_id,
            name=asset.get("name", ""),
            hook=asset.get("hook", ""),
            angle=asset.get("angle", ""),
        )
        results.append({
            "adgroup_id": adgroup_id,
            "creative_name": asset.get("name", ""),
            "video_id": video_id,
            "ad_id": ad_id,
        })
    return results


# ── ROAS reporting ─────────────────────────────────────────────────────────────

@safe_call(default=dict)
def fetch_roas(campaign_ids: list[str], date: str | None = None) -> dict[str, float]:
    """Return {campaign_id → roas} for the given date (defaults to today)."""
    if not campaign_ids:
        return {}
    if _DRY_RUN:
        # Simulate realistic ROAS for dry-run testing
        import random
        return {cid: round(random.uniform(0.8, 2.5), 4) for cid in campaign_ids}
    import datetime
    today = date or datetime.date.today().strftime("%Y-%m-%d")
    resp = _get("/reports/integrated/get/", {
        "advertiser_id": os.getenv("TIKTOK_ADVERTISER_ID", ""),
        "report_type": "BASIC",
        "dimensions": ["campaign_id"],
        "metrics": ["spend", "revenue"],
        "start_date": today,
        "end_date": today,
        "filtering": [{"field_name": "campaign_id", "filter_type": "IN",
                       "filter_value": campaign_ids}],
    })
    result = {}
    for row in resp.get("data", {}).get("list", []):
        dims = row.get("dimensions", {})
        metrics = row.get("metrics", {})
        cid = str(dims.get("campaign_id", ""))
        spend   = float(metrics.get("spend", 0) or 0)
        revenue = float(metrics.get("revenue", 0) or 0)
        result[cid] = round(revenue / spend, 4) if spend > 0 else 0.0
    return result


# ── anomaly detection + auto-actions ─────────────────────────────────────────

def check_and_act(
    campaign_id: str,
    spend: float,
    budget: float,
    roas: float,
) -> str:
    """Inspect spend/ROAS and fire kill or scale as needed. Returns action taken."""
    global _roas_streaks

    # Kill-switch: overspend with bad ROAS
    if spend > budget * _KILL_SPEND_RATIO and roas < _KILL_ROAS_FLOOR:
        pause_campaign(campaign_id)
        _roas_streaks.pop(campaign_id, None)
        return "killed"

    # Scale-up: consecutive win streak
    streak = _roas_streaks.setdefault(campaign_id, [])
    streak.append(roas)
    if len(streak) > _SCALE_WIN_STREAK:
        streak.pop(0)
    if len(streak) >= _SCALE_WIN_STREAK and all(r >= 1.5 for r in streak):
        new_budget = round(budget * _SCALE_MULTIPLIER, 2)
        scale_budget(campaign_id, new_budget, current_budget=budget)
        _roas_streaks[campaign_id] = []  # reset streak after scaling
        return f"scaled_to_{new_budget}"

    return "hold"


# ── playbook → campaign launcher ──────────────────────────────────────────────

def launch_from_playbook(playbook: dict, phase: str = "EXPLORE") -> dict:
    """Create a full campaign from a playbook dict. Safe in dry-run mode.

    Returns a summary dict with campaign_id, adgroup_id, ad_ids.
    """
    product = playbook.get("product", "unknown")
    hooks   = playbook.get("top_hooks", ["This changed everything…"])
    angles  = playbook.get("top_angles", ["Problem-solution"])
    budget  = playbook.get("estimated_roas", 1.0) * _BUDGET_DAILY

    if not _DRY_RUN:
        from backend.risk.gate import check_spend
        gate = check_spend(budget)
        if not gate["allowed"]:
            _log.warning("playbook_launch_blocked_by_risk_gate product=%s reason=%s",
                        product, gate["reason"])
            return {"status": "error", "reason": f"risk_gate_blocked: {gate['reason']}"}
        budget = gate["adjusted_amount"]

    campaign_id = create_campaign(
        name=f"marketos_{product}_{phase}_{int(time.time())}",
        budget=round(budget, 2),
    )
    if not campaign_id:
        return {"status": "error", "reason": "campaign_create_failed"}

    adgroup_id = create_ad_group(campaign_id, name=f"ag_{product}", daily_budget=budget)
    ad_ids = []
    for i, hook in enumerate(hooks[:3]):
        angle = angles[i % len(angles)] if angles else ""
        ad_id = create_ad(
            adgroup_id=adgroup_id,
            creative_id=f"creative_{product}_{i}",
            name=f"ad_{product}_{i}",
            hook=hook,
            angle=angle,
        )
        if ad_id:
            ad_ids.append(ad_id)

    if not _DRY_RUN:
        from backend.risk.gate import record_spend
        record_spend(budget)

    return {
        "status": "ok",
        "dry_run": _DRY_RUN,
        "campaign_id": campaign_id,
        "adgroup_id": adgroup_id,
        "ad_ids": ad_ids,
        "product": product,
        "budget": round(budget, 2),
    }
