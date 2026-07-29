"""core.ads.campaign_builder — build a structured campaign payload."""
from __future__ import annotations

from typing import Any


def build_campaign(
    product: str,
    creatives: list[Any],
    budget: float = 10.0,
    targeting: str = "broad",
) -> dict[str, Any]:
    """Return a campaign payload dict.

    Parameters
    ----------
    product:
        Product name to feature in the campaign name.
    creatives:
        List of creative dicts or video URLs to attach.
    budget:
        Daily budget in USD (default ``10.0``).
    targeting:
        Targeting description string (default ``"broad"``).

    Returns
    -------
    dict
        Campaign payload with ``name``, ``budget``, ``targeting``, and
        ``creatives`` keys.
    """
    return {
        "name": f"campaign_{product}",
        "budget": budget,
        "targeting": targeting,
        "creatives": list(creatives),
    }
