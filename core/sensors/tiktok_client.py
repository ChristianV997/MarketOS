"""core.sensors.tiktok_client — fetch trending TikTok videos via RapidAPI."""
from __future__ import annotations

import os
from typing import Any

_API_URL = "https://tiktok-api23.p.rapidapi.com/api/trending/feed"
_API_HOST = "tiktok-api23.p.rapidapi.com"


def fetch_trending(count: int = 30) -> list[dict[str, Any]]:
    """Fetch trending TikTok videos.

    Requires the environment variable ``RAPIDAPI_KEY`` to be set.

    Parameters
    ----------
    count:
        Number of trending videos to request.

    Returns
    -------
    list[dict]
        Each dict contains ``id``, ``text``, ``views``, ``likes``,
        ``comments``, and ``shares``.
    """
    try:
        import requests  # type: ignore[import]
    except ImportError:
        return []

    key = os.environ.get("RAPIDAPI_KEY", "")
    if not key:
        return []

    headers = {
        "X-RapidAPI-Key": key,
        "X-RapidAPI-Host": _API_HOST,
    }
    try:
        res = requests.get(_API_URL, headers=headers, params={"count": count}, timeout=10)
        data = res.json()
    except Exception:
        return []

    videos = []
    for item in data.get("data", []):
        stats = item.get("stats", {})
        videos.append(
            {
                "id": item.get("id"),
                "text": item.get("desc", ""),
                "views": stats.get("playCount", 0),
                "likes": stats.get("diggCount", 0),
                "comments": stats.get("commentCount", 0),
                "shares": stats.get("shareCount", 0),
            }
        )
    return videos
