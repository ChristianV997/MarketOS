"""core.reports.top10 — generate a ranked top-10 list from scored signals."""
from __future__ import annotations

from typing import Any


def top10(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the top-10 highest-scored signals.

    Parameters
    ----------
    signals:
        List of signal dicts each containing a ``"score"`` key.

    Returns
    -------
    list[dict]
        Up to 10 signals sorted by descending score.
    """
    ranked = sorted(signals, key=lambda x: float(x.get("score", 0)), reverse=True)
    return ranked[:10]
