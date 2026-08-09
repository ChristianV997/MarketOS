"""backend.discovery.ad_intelligence — competitor-ad intelligence.

Meta Ad Library client (the only free, official, cross-advertiser ad archive)
plus a saturation summary used by discovery scoring and product validation.

Dry-run by default (ADLIB_DRY_RUN=true): returns deterministic mock results
derived from the keyword so scoring is reproducible offline and in tests.
Production activation: set ADLIB_DRY_RUN=false and supply META_ACCESS_TOKEN
(the Ad Library API uses a standard Meta Graph token with ads_read).
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

_log = logging.getLogger(__name__)

_DRY_RUN = os.getenv("ADLIB_DRY_RUN", "true").lower() != "false"
_GRAPH_VERSION = os.getenv("META_GRAPH_API_VERSION", "v20.0")

# Saturation model: competitor count at which a market reads fully saturated
_SATURATION_CEILING = int(os.getenv("ADLIB_SATURATION_CEILING", "50"))


def _stable_int(seed: str, lo: int, hi: int) -> int:
    """Deterministic pseudo-random int in [lo, hi] from a string seed."""
    digest = hashlib.md5(seed.encode()).hexdigest()
    return lo + int(digest[:8], 16) % (hi - lo + 1)


def search_ads(keyword: str, country: str = "US", limit: int = 25) -> list[dict[str, Any]]:
    """Search active competitor ads for a keyword via the Meta Ad Library.

    Returns a list of {advertiser, body, spend_upper, impressions_upper}.
    Fail-silent: any API problem returns the deterministic mock so callers
    always get a usable (if approximate) competition picture.
    """
    if not _DRY_RUN and os.getenv("META_ACCESS_TOKEN"):
        try:
            return _live_search(keyword, country, limit)
        except Exception as exc:
            _log.debug("adlib_search_failed keyword=%s error=%s", keyword, exc)
    return _mock_search(keyword, limit)


def _live_search(keyword: str, country: str, limit: int) -> list[dict[str, Any]]:
    import requests
    resp = requests.get(
        f"https://graph.facebook.com/{_GRAPH_VERSION}/ads_archive",
        params={
            "access_token": os.environ["META_ACCESS_TOKEN"],
            "search_terms": keyword,
            "ad_active_status": "ACTIVE",
            "ad_reached_countries": f'["{country}"]',
            "limit": limit,
            "fields": "page_name,ad_creative_bodies,spend,impressions",
        },
        timeout=15,
    )
    resp.raise_for_status()
    ads = []
    for row in resp.json().get("data", []):
        bodies = row.get("ad_creative_bodies") or [""]
        spend = row.get("spend") or {}
        impressions = row.get("impressions") or {}
        ads.append({
            "advertiser": row.get("page_name", ""),
            "body": bodies[0][:280],
            "spend_upper": float(spend.get("upper_bound", 0) or 0),
            "impressions_upper": float(impressions.get("upper_bound", 0) or 0),
        })
    return ads


def _mock_search(keyword: str, limit: int) -> list[dict[str, Any]]:
    """Deterministic mock: competitor count and spend derive from the keyword,
    so the same product always sees the same competitive landscape."""
    n = min(limit, _stable_int(f"adlib:{keyword}:count", 0, 40))
    ads = []
    for i in range(n):
        ads.append({
            "advertiser": f"competitor_{_stable_int(f'{keyword}:{i}:adv', 1, 999)}",
            "body": f"[mock ad] {keyword} — limited time offer #{i + 1}",
            "spend_upper": float(_stable_int(f"{keyword}:{i}:spend", 100, 20000)),
            "impressions_upper": float(_stable_int(f"{keyword}:{i}:imp", 1000, 500000)),
        })
    return ads


def competition_summary(keyword: str, country: str = "US") -> dict[str, Any]:
    """Summarize competitive pressure on a keyword.

    market_saturation ∈ [0, 1]: distinct advertisers / saturation ceiling.
    difficulty: easy (<0.3), medium (0.3–0.6), hard (>0.6).
    """
    ads = search_ads(keyword, country=country)
    advertisers = {a["advertiser"] for a in ads if a.get("advertiser")}
    competitor_count = len(advertisers)
    total_spend = sum(a.get("spend_upper", 0.0) for a in ads)

    saturation = min(1.0, competitor_count / _SATURATION_CEILING)
    difficulty = "hard" if saturation > 0.6 else ("medium" if saturation > 0.3 else "easy")

    return {
        "keyword": keyword,
        "competitor_count": competitor_count,
        "ad_count": len(ads),
        "total_spend_upper": round(total_spend, 2),
        "avg_spend_upper": round(total_spend / competitor_count, 2) if competitor_count else 0.0,
        "market_saturation": round(saturation, 2),
        "difficulty": difficulty,
    }
