"""ingest — aggregate signals from all 7 sources."""
from __future__ import annotations
import asyncio
from .base import BaseSignal
from .tiktok import ingest_tiktok
from .youtube import ingest_youtube
from .meta import ingest_meta
from .google import ingest_google
from .amazon import ingest_amazon
from .google_trends import ingest_google_trends
from .linkedin import ingest_linkedin


async def _run(fn, *args):
    return await asyncio.get_event_loop().run_in_executor(None, fn, *args)


_SOURCE_CAP = 4


async def ingest_all() -> list[BaseSignal]:
    results = await asyncio.gather(
        _run(ingest_tiktok,        "trending products"),
        _run(ingest_youtube,       "make money online"),
        _run(ingest_meta,          "facebook trending"),
        _run(ingest_google,        "google search trends"),
        _run(ingest_amazon,        "amazon best sellers"),
        _run(ingest_google_trends, "google trends rising"),
        _run(ingest_linkedin,      "linkedin trending business"),
    )
    signals: list[BaseSignal] = []
    for batch in results:
        capped = sorted(batch, key=lambda s: s["engagement"], reverse=True)[:_SOURCE_CAP]
        signals.extend(capped)
    return signals


def ingest_all_sync() -> list[BaseSignal]:
    return asyncio.run(ingest_all())
