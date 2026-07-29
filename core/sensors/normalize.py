"""core.sensors.normalize — normalise raw platform signals to a unified schema."""
from __future__ import annotations

from typing import Any


def normalize_tiktok(video: dict[str, Any]) -> dict[str, Any]:
    """Convert a raw TikTok video dict to the standard signal schema.

    Parameters
    ----------
    video:
        Raw dict from :func:`~core.sensors.tiktok_client.fetch_trending`.

    Returns
    -------
    dict
        Normalised signal with keys ``source``, ``text``, ``views``,
        ``likes``, and ``comments``.
    """
    return {
        "source": "tiktok",
        "text": video.get("text", ""),
        "views": int(video.get("views", 0)),
        "likes": int(video.get("likes", 0)),
        "comments": int(video.get("comments", 0)),
    }
