"""core.ads.google — Google Ads API connector stub."""
from __future__ import annotations

from typing import Any


def create_campaign(client: Any | None = None) -> dict[str, Any]:
    """Create a Google Ads campaign.

    This is a minimal stub.  Implement the full campaign creation by passing
    an initialised ``GoogleAdsClient`` via *client* and expanding the function
    body to use the Google Ads Python SDK.

    Parameters
    ----------
    client:
        Initialised ``google.ads.googleads.client.GoogleAdsClient`` instance,
        or ``None`` when running offline / in tests.

    Returns
    -------
    dict
        Result dict (``{"status": "stub"}`` when no client is provided).
    """
    if client is None:
        return {"status": "stub"}

    # --- integrate Google Ads SDK here ---
    return {"status": "ok"}
