"""core.pipeline.execution — end-to-end creative → ad execution pipeline.

Step 65: Creative Generation + Ad Execution Layer
"""
from __future__ import annotations

import os
from typing import Any

from core.creative.generator import generate_creatives
from core.creative.video import generate_video
from core.ads.campaign_builder import build_campaign
from core.ads.tiktok import create_campaign as tiktok_create_campaign


def execute(candidate: dict[str, Any]) -> dict[str, Any]:
    """Generate creatives, build a campaign, and launch on TikTok.

    Parameters
    ----------
    candidate:
        Selection candidate dict containing ``"product"`` and ``"angle"`` keys.

    Returns
    -------
    dict
        API response from the ad platform (or an error/dry-run dict).
    """
    product = candidate.get("product", "product")
    angle = candidate.get("angle", "general")

    creatives = generate_creatives(product, angle)
    videos = [generate_video(c) for c in creatives]
    campaign = build_campaign(product, videos)

    token = os.environ.get("TIKTOK_TOKEN", "")
    if not token:
        return {"status": "dry_run", "campaign": campaign}

    return tiktok_create_campaign(token, campaign)
