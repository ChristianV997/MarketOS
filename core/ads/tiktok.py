"""core.ads.tiktok — TikTok Ads API connector."""
from __future__ import annotations

from typing import Any


def create_campaign(token: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Create a TikTok Ads campaign.

    Parameters
    ----------
    token:
        TikTok Ads API access token.
    payload:
        Campaign creation payload per the TikTok Marketing API spec.

    Returns
    -------
    dict
        API response dict, or an error dict when the request fails.
    """
    try:
        import requests  # type: ignore[import]
    except ImportError:
        return {"error": "requests not installed"}

    url = "https://business-api.tiktok.com/open_api/v1.3/campaign/create/"
    headers = {"Access-Token": token}
    try:
        return requests.post(url, json=payload, headers=headers, timeout=10).json()
    except Exception as exc:
        return {"error": str(exc)}
