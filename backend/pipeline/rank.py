"""rank — sort signals by engagement descending."""
from __future__ import annotations
from backend.signals.base import BaseSignal


def rank_signals(signals: list[BaseSignal]) -> list[BaseSignal]:
    return sorted(signals, key=lambda s: s["engagement"], reverse=True)
