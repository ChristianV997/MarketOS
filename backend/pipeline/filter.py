"""filter — keyword + engagement gate."""
from __future__ import annotations
from backend.signals.base import BaseSignal

FILTER_KEYWORDS = [
    "buy", "price", "worth", "save", "make money", "earn",
    "hack", "secret", "tool", "productivity", "automation", "scale", "growth",
]

ENGAGEMENT_THRESHOLD = 0.50


def filter_signals(signals: list[BaseSignal]) -> list[BaseSignal]:
    result = []
    for s in signals:
        if s["engagement"] < ENGAGEMENT_THRESHOLD:
            continue
        text_lower = s["raw_text"].lower()
        if any(kw in text_lower for kw in FILTER_KEYWORDS):
            result.append(s)
    return result
