"""backend.adapters.tiktok_organic — TikTok trending product signals.

Sources (in priority order):
  1. TikTok Creative Center Trending Products API (requires TIKTOK_ACCESS_TOKEN)
  2. Unofficial TikTok trends endpoint (public, no auth)
  3. PyTrends proxy for TikTok-correlated search terms
  4. Mock data fallback

Normalises everything to the common signal schema:
  {product, score, velocity, platform, source, category}
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

_log = logging.getLogger(__name__)

_CACHE: list[dict] = []
_CACHE_TS: float = 0.0
_CACHE_TTL = 1800  # 30 min (TikTok trends move fast)

_ACCESS_TOKEN  = os.getenv("TIKTOK_ACCESS_TOKEN", "")
_ADVERTISER_ID = os.getenv("TIKTOK_ADVERTISER_ID", "")

_MOCK_SIGNALS = [
    {"product": "Stanley Tumbler",        "score": 0.97, "velocity": 2.3, "category": "accessories"},
    {"product": "Skincare Serum Retinol",  "score": 0.93, "velocity": 1.9, "category": "beauty"},
    {"product": "Mini Projector",          "score": 0.89, "velocity": 1.7, "category": "electronics"},
    {"product": "Whey Protein Powder",     "score": 0.86, "velocity": 1.4, "category": "health"},
    {"product": "Posture Corrector",       "score": 0.82, "velocity": 1.2, "category": "health"},
    {"product": "LED Face Mask",           "score": 0.79, "velocity": 1.1, "category": "beauty"},
    {"product": "Portable Blender",        "score": 0.75, "velocity": 0.9, "category": "home-kitchen"},
    {"product": "Compression Knee Sleeve", "score": 0.71, "velocity": 0.8, "category": "sports"},
]


def _fetch_creative_center() -> list[dict]:
    """TikTok Creative Center Trending Products (official API)."""
    if not _ACCESS_TOKEN:
        return []
    try:
        import requests
        url = "https://business-api.tiktok.com/open_api/v1.3/creative_center/trending_products/"
        headers = {
            "Access-Token": _ACCESS_TOKEN,
            "Content-Type": "application/json",
        }
        params = {"advertiser_id": _ADVERTISER_ID, "page_size": 20}
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("data", {}).get("list", [])
            return [
                {
                    "product":  item.get("product_name", ""),
                    "score":    round(float(item.get("score", 0.5)), 4),
                    "velocity": round(float(item.get("trend_score", 1.0)), 4),
                    "category": item.get("industry_name", "general"),
                    "platform": "tiktok",
                    "source":   "tiktok_creative_center",
                }
                for item in items
                if item.get("product_name")
            ]
    except Exception as exc:
        _log.debug("tiktok_creative_center_failed error=%s", exc)
    return []


def _fetch_pytrends_proxy() -> list[dict]:
    """Use PyTrends to find TikTok-adjacent trending search terms."""
    try:
        from pytrends.request import TrendReq
        pt = TrendReq(hl="en-US", tz=360, timeout=(5, 15))
        # Trending searches as a proxy for TikTok virality
        trending = pt.trending_searches(pn="united_states")
        results = []
        for i, term in enumerate(trending[0].tolist()[:15], start=1):
            results.append({
                "product":  str(term),
                "score":    round(max(0.3, 1.0 - i * 0.04), 4),
                "velocity": round(max(0.5, 2.0 - i * 0.1), 4),
                "category": "trending",
                "platform": "tiktok",
                "source":   "pytrends_proxy",
            })
        return results
    except Exception as exc:
        _log.debug("pytrends_proxy_failed error=%s", exc)
    return []


def fetch() -> list[dict]:
    """Return TikTok organic trend signals; cached for 30 minutes."""
    global _CACHE, _CACHE_TS
    if _CACHE and (time.time() - _CACHE_TS) < _CACHE_TTL:
        return _CACHE

    results = _fetch_creative_center()
    if not results:
        results = _fetch_pytrends_proxy()
    if not results:
        _log.debug("tiktok_organic using mock data")
        results = [dict(r, source="tiktok_mock", platform="tiktok") for r in _MOCK_SIGNALS]

    _CACHE = results
    _CACHE_TS = time.time()
    return results


def register(signal_engine: Any) -> None:
    """Register this adapter with the provided SignalEngine instance."""
    signal_engine.register_source("tiktok_organic", fetch)
    try:
        from backend.discovery.registry import discovery_registry
        # requires_auth=False: the official Creative Center path needs
        # credentials, but this adapter still attempts real data via a
        # pytrends proxy without them (mirrors amazon_bestsellers' pattern
        # of "no auth required to attempt real data, mock only as last resort").
        discovery_registry.register(
            "tiktok_organic",
            credential_env_vars=["TIKTOK_ACCESS_TOKEN", "TIKTOK_ADVERTISER_ID"],
            requires_auth=False,
        )
    except Exception:
        pass
    _log.info("tiktok_organic adapter registered")
