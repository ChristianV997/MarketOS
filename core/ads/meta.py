"""core.ads.meta — Meta (Facebook) Ads API connector."""
from __future__ import annotations

from typing import Any


def create_ad(
    account_id: str, token: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Create a Meta Ads ad object.

    Parameters
    ----------
    account_id:
        Meta Ads account ID (without the ``act_`` prefix).
    token:
        Facebook access token.
    payload:
        Ad creation payload per the Graph API spec.

    Returns
    -------
    dict
        API response dict, or an error dict when the request fails.
    """
    try:
        import requests  # type: ignore[import]
    except ImportError:
        return {"error": "requests not installed"}

    url = f"https://graph.facebook.com/v18.0/{account_id}/ads"
    try:
        return requests.post(url, data=payload, timeout=10).json()
    except Exception as exc:
        return {"error": str(exc)}
