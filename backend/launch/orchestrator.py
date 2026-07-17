"""backend.launch.orchestrator — turn a built product into live campaigns.

Reuses the existing platform integrations (backend.integrations.tiktok_ads,
backend.integrations.meta_ads_client) — both dry-run safe by default — and
splits the daily budget across the requested platforms.

Per-platform failure is isolated: one platform erroring never blocks the
others, and the summary reports exactly what went live where.
"""
from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger(__name__)

# Budget split when launching on both platforms; TikTok gets the edge because
# dropship CPMs and organic spillover historically run cheaper there.
_SPLIT = {"tiktok": 0.55, "meta": 0.45}


def launch_product(
    build: dict[str, Any],
    budget_daily: float = 50.0,
    platforms: tuple[str, ...] = ("tiktok", "meta"),
) -> dict[str, Any]:
    """Launch campaigns for a built product (output of build_product()).

    Returns {status, product, campaigns: [{platform, campaign_id, ...}], total_budget}.
    status is "ok" if at least one platform launched, else "error".
    """
    product = build.get("product", "unknown")
    page_url = (build.get("page") or {}).get("url", "")
    ad_copy = build.get("ad_copy") or {}

    weights = {p: _SPLIT.get(p, 1.0 / len(platforms)) for p in platforms}
    total_w = sum(weights.values()) or 1.0

    campaigns: list[dict[str, Any]] = []
    for platform in platforms:
        budget = round(budget_daily * weights[platform] / total_w, 2)
        try:
            if platform == "tiktok":
                campaigns.append(_launch_tiktok(product, page_url, budget,
                                                ad_copy.get("tiktok") or {}))
            elif platform == "meta":
                campaigns.append(_launch_meta(product, page_url, budget,
                                              ad_copy.get("meta") or {}))
            else:
                _log.debug("launch_unknown_platform platform=%s", platform)
        except Exception as exc:
            _log.exception("launch_platform_failed platform=%s product=%s", platform, product)
            campaigns.append({"platform": platform, "status": "error", "error": str(exc)})

    live = [c for c in campaigns if c.get("status") == "live"]
    return {
        "status": "ok" if live else "error",
        "product": product,
        "campaigns": campaigns,
        "live_count": len(live),
        "total_budget": round(sum(c.get("budget", 0.0) for c in live), 2),
    }


def _launch_tiktok(product: str, page_url: str, budget: float,
                   copy: dict[str, Any]) -> dict[str, Any]:
    from backend.integrations import tiktok_ads

    campaign_id = tiktok_ads.create_campaign(
        name=f"ds_{product[:40]}_tiktok", budget=budget)
    if not campaign_id:
        return {"platform": "tiktok", "status": "error", "error": "campaign_create_failed"}

    adgroup_id = tiktok_ads.create_ad_group(
        campaign_id, name=f"ag_{product[:40]}", daily_budget=budget)

    hooks = copy.get("hooks") or [f"Meet the {product}"]
    angles = copy.get("angles") or ["problem-solution"]
    ad_ids = []
    for i, hook in enumerate(hooks[:3]):
        ad_id = tiktok_ads.create_ad(
            adgroup_id=adgroup_id,
            creative_id=f"ds_{product[:30]}_{i}",
            name=f"ad_{product[:30]}_{i}",
            hook=hook,
            angle=angles[i % len(angles)],
        )
        if ad_id:
            ad_ids.append(ad_id)

    return {
        "platform": "tiktok",
        "status": "live" if ad_ids else "error",
        "campaign_id": campaign_id,
        "adgroup_id": adgroup_id,
        "ad_ids": ad_ids,
        "budget": budget,
        "hook": hooks[0],
        "angle": angles[0],
    }


def _launch_meta(product: str, page_url: str, budget: float,
                 copy: dict[str, Any]) -> dict[str, Any]:
    from backend.integrations import meta_ads_client as meta

    campaign_id = meta.create_campaign(
        name=f"ds_{product[:40]}_meta", daily_budget=budget)
    if not campaign_id:
        return {"platform": "meta", "status": "error", "error": "campaign_create_failed"}

    ad_set_id = meta.create_ad_set(campaign_id, name=f"as_{product[:40]}",
                                   daily_budget=budget)

    headlines = copy.get("headlines") or [f"{product} — Shop Now"]
    hooks = copy.get("hooks") or [f"Meet the {product}"]
    angles = copy.get("angles") or ["problem-solution"]
    ad_ids = []
    for i, headline in enumerate(headlines[:3]):
        ad_id = meta.create_ad(
            ad_set_id=ad_set_id,
            name=f"ad_{product[:30]}_{i}",
            headline=headline,
            body=hooks[i % len(hooks)],
            link_url=page_url,
        )
        if ad_id:
            ad_ids.append(ad_id)

    return {
        "platform": "meta",
        "status": "live" if ad_ids else "error",
        "campaign_id": campaign_id,
        "adgroup_id": ad_set_id,
        "ad_ids": ad_ids,
        "budget": budget,
        "hook": hooks[0],
        "angle": angles[0],
    }
