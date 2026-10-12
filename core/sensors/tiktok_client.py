"""core.sensors.tiktok_client — offline compatibility shim.

``fetch_trending`` used to call a third-party trending feed when a credential
was present. That live path is retired. The function always returns an empty
list so ``core.jobs.daily_research`` keeps its unconfigured contract.

This module is not a discovery source. The registered adapter is
``backend.adapters.tiktok_organic``.
"""
from __future__ import annotations

from typing import Any


def fetch_trending(count: int = 30) -> list[dict[str, Any]]:
    """Return no videos.

    ``count`` is accepted for existing callers and ignored. This function
    does not look up environment variables and does not perform I/O.
    """
    if not isinstance(count, int):
        return []
    return []
