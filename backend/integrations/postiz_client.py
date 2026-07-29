"""backend.integrations.postiz_client — organic social publishing via Postiz.

Postiz (github.com/gitroomhq/postiz-app) is an open-source, self-hosted
social scheduling service with official OAuth integrations for ~33
platforms (TikTok, Instagram, YouTube, Reddit, Pinterest, X, ...). Running
it as a Docker sidecar and consuming its REST API buys the entire
organic-publishing surface with one integration, instead of per-platform
app registrations.

This client is the ONLY module that talks to Postiz; the rest of the
system publishes through it so a direct-platform client can be swapped in
later without touching callers.

Dry-run: when POSTIZ_URL/POSTIZ_API_KEY are unset or ORGANIC_DRY_RUN=true
(the default), no network is touched — posts get deterministic dry ids and
metrics are deterministic per post id (the suppliers-style _stable_fraction
idiom), so the whole organic loop is rehearsable offline and in tests.

Setup (documented for go-live):
    docker run -d -p 5000:5000 ghcr.io/gitroomhq/postiz-app
    export POSTIZ_URL=http://localhost:5000
    export POSTIZ_API_KEY=<from Postiz settings>
    export ORGANIC_DRY_RUN=false
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

from backend.patterns.safe_call import safe_call

_log = logging.getLogger(__name__)

_POST_SEQ = 0


def _dry_run() -> bool:
    if os.getenv("ORGANIC_DRY_RUN", "true").lower() != "false":
        return True
    return not (os.getenv("POSTIZ_URL") and os.getenv("POSTIZ_API_KEY"))


def is_configured() -> bool:
    """True when a live Postiz endpoint is configured AND dry-run is off."""
    return not _dry_run()


def _stable_fraction(seed: str) -> float:
    digest = hashlib.md5(seed.encode()).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def _next_dry_post_id(text: str) -> str:
    global _POST_SEQ
    _POST_SEQ += 1
    stem = hashlib.md5(text.encode()).hexdigest()[:8]
    return f"dry_post_{stem}_{_POST_SEQ}"


def _headers() -> dict[str, str]:
    return {
        "Authorization": os.getenv("POSTIZ_API_KEY", ""),
        "Content-Type": "application/json",
    }


@safe_call(default=lambda: {"status": "error", "post_id": "", "dry_run": True})
def create_post(
    text: str,
    platforms: list[str] | None = None,
    media_url: str = "",
    schedule_at: str | None = None,
) -> dict[str, Any]:
    """Create (or schedule) an organic post across *platforms*.

    Returns {status, post_id, platforms, dry_run}.
    """
    platforms = platforms or ["tiktok"]

    if _dry_run():
        post_id = _next_dry_post_id(text)
        _log.info("organic_dry_post id=%s platforms=%s len=%d",
                  post_id, platforms, len(text))
        return {"status": "ok", "post_id": post_id,
                "platforms": platforms, "dry_run": True}

    import requests
    base = os.getenv("POSTIZ_URL", "").rstrip("/")
    payload: dict[str, Any] = {
        "content": text,
        "platforms": platforms,
    }
    if media_url:
        payload["media"] = [{"url": media_url}]
    if schedule_at:
        payload["scheduleDate"] = schedule_at

    resp = requests.post(f"{base}/api/public/v1/posts",
                         json=payload, headers=_headers(), timeout=15)
    resp.raise_for_status()
    data = resp.json()
    post_id = str(data.get("id") or data.get("postId") or "")
    return {"status": "ok", "post_id": post_id,
            "platforms": platforms, "dry_run": False}


@safe_call(default=lambda: {"impressions": 0, "likes": 0, "comments": 0,
                            "shares": 0, "dry_run": True})
def get_post_metrics(post_id: str) -> dict[str, Any]:
    """Fetch engagement metrics for a published post.

    Returns {impressions, likes, comments, shares, dry_run}.
    Dry-run metrics are deterministic per post_id so tests and shadow-mode
    rehearsals are reproducible: impressions 500-10500, engagement drawn
    from stable hash fractions.
    """
    if _dry_run():
        f1 = _stable_fraction(f"{post_id}:imp")
        f2 = _stable_fraction(f"{post_id}:eng")
        impressions = int(500 + f1 * 10_000)
        engaged = int(impressions * (0.01 + f2 * 0.09))  # 1-10% engagement
        return {
            "impressions": impressions,
            "likes": int(engaged * 0.7),
            "comments": int(engaged * 0.15),
            "shares": int(engaged * 0.15),
            "dry_run": True,
        }

    import requests
    base = os.getenv("POSTIZ_URL", "").rstrip("/")
    resp = requests.get(f"{base}/api/public/v1/posts/{post_id}/metrics",
                        headers=_headers(), timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return {
        "impressions": int(data.get("impressions", 0) or 0),
        "likes": int(data.get("likes", 0) or 0),
        "comments": int(data.get("comments", 0) or 0),
        "shares": int(data.get("shares", 0) or 0),
        "dry_run": False,
    }
