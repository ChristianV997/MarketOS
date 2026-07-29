"""dedup — remove duplicate signals by normalized key."""
from __future__ import annotations
import re
from backend.signals.base import BaseSignal


def normalized_key(s: BaseSignal) -> str:
    """Stable dedup key: source + first 60 chars of lowercased, collapsed raw_text."""
    text = re.sub(r"\s+", " ", s["raw_text"].strip().lower())[:60]
    return f"{s['source']}::{text}"


def dedup_signals(signals: list[BaseSignal]) -> list[BaseSignal]:
    """Return signals with duplicate keys removed (first occurrence wins)."""
    seen: set[str] = set()
    result: list[BaseSignal] = []
    for s in signals:
        key = normalized_key(s)
        if key not in seen:
            seen.add(key)
            result.append(s)
    return result
