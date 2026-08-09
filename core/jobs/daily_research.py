"""core.jobs.daily_research — cron-style daily research pipeline."""
from __future__ import annotations

from core.sensors.tiktok_client import fetch_trending
from core.sensors.normalize import normalize_tiktok
from core.sensors.scoring import score
from core.reports.top10 import top10


def run() -> list[dict]:
    """Fetch trending TikTok signals, score them, and return the top-10 report.

    Returns
    -------
    list[dict]
        Top-10 ranked signals (may be empty when no API key is configured).
    """
    raw = fetch_trending()
    signals = [normalize_tiktok(v) for v in raw]
    for s in signals:
        s["score"] = score(s)
    report = top10(signals)
    return report
