"""backend.optimization.budget_actuator — turn a scaling decision into a
real platform action.

Before this module, backend.optimization.budget_scaling.compute_scaling_decisions
correctly identified which campaigns to kill/scale/scale-down, but
apply_scaling_decisions() only wrote the decision to a JSONL log — nothing
ever called pause_campaign()/scale_budget() on the actual platform. A
campaign flagged "kill" (ROAS < 0.5) kept spending real money until a human
manually intervened via a separate, unrelated endpoint.

apply_decision() dispatches by decision["platform"] to the matching
actuator (tiktok_ads.pause_campaign/scale_budget,
meta_ads_client.pause_campaign/update_ad_set_budget) — each of those is
already risk-gated internally (backend.risk.gate), so no separate gate
call is needed here. Actuation itself is gated by BUDGET_APPLY_LIVE
(default false, same shadow-then-flip pattern as capital_policy.py):
apply_scaling_decisions() always journals what WOULD happen, and only
calls apply_decision() for real when the flag is live.
"""
from __future__ import annotations

import logging
import os
from typing import Any

_log = logging.getLogger(__name__)


def live() -> bool:
    return os.getenv("BUDGET_APPLY_LIVE", "false").lower() == "true"


def apply_decision(decision: dict[str, Any], adgroup_id: str = "") -> dict[str, Any]:
    """Actuate one scaling decision against its real platform.

    *adgroup_id* is the Meta ad-set id (Meta's budget lives on the ad set,
    not the campaign) — required for scale_up/scale_down on Meta, unused
    for TikTok (whose budget lives on the campaign) and for kill (Meta
    pauses at the campaign level). Never raises; always returns a result
    dict with a "status" key.
    """
    action = decision.get("action", "maintain")
    platform = decision.get("platform", "")
    campaign_id = decision.get("campaign_id", "")

    if action == "maintain" or not campaign_id:
        return {"campaign_id": campaign_id, "action": action, "status": "skipped"}

    if platform not in ("tiktok", "meta"):
        return {"campaign_id": campaign_id, "action": action,
                "status": "error", "error": f"unknown_platform:{platform}"}

    try:
        if action == "kill":
            ok = _pause(platform, campaign_id)
        elif action in ("scale_up", "scale_down"):
            if platform == "meta" and not adgroup_id:
                return {"campaign_id": campaign_id, "action": action,
                        "status": "error", "error": "missing_adgroup_id"}
            ok = _scale(platform, campaign_id, adgroup_id,
                       decision.get("new_budget", 0.0), decision.get("current_budget", 0.0))
        else:
            ok = False
        return {"campaign_id": campaign_id, "action": action,
                "status": "ok" if ok else "error"}
    except Exception as exc:
        _log.error("budget_actuation_failed campaign=%s platform=%s action=%s error=%s",
                   campaign_id, platform, action, exc, exc_info=True)
        return {"campaign_id": campaign_id, "action": action,
                "status": "error", "error": str(exc)}


def _pause(platform: str, campaign_id: str) -> bool:
    if platform == "tiktok":
        from backend.integrations import tiktok_ads
        return tiktok_ads.pause_campaign(campaign_id)
    from backend.integrations import meta_ads_client as meta
    return meta.pause_campaign(campaign_id)


def _scale(platform: str, campaign_id: str, adgroup_id: str,
          new_budget: float, current_budget: float) -> bool:
    if platform == "tiktok":
        from backend.integrations import tiktok_ads
        return tiktok_ads.scale_budget(campaign_id, new_budget, current_budget=current_budget)
    from backend.integrations import meta_ads_client as meta
    return meta.update_ad_set_budget(adgroup_id, new_budget, current_budget=current_budget)


def apply_decisions_live(decisions: list[dict[str, Any]],
                         adgroup_ids: dict[str, str] | None = None) -> dict[str, Any]:
    """Actuate every decision. *adgroup_ids* maps campaign_id -> Meta ad-set
    id, for decisions whose platform is "meta". Returns a summary dict."""
    adgroup_ids = adgroup_ids or {}
    results = [
        apply_decision(d, adgroup_id=adgroup_ids.get(d.get("campaign_id", ""), ""))
        for d in decisions
    ]
    applied = sum(1 for r in results if r["status"] == "ok")
    errors = sum(1 for r in results if r["status"] == "error")
    return {"status": "ok", "total": len(results), "applied": applied,
           "errors": errors, "results": results}
