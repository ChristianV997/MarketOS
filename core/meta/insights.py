"""core.meta.insights — detect cross-playbook patterns from execution history."""
from __future__ import annotations

from typing import Any


def detect_patterns(history: list[dict[str, Any]]) -> list[str]:
    """Scan *history* records and return human-readable insight strings.

    Each history record is expected to contain ``geo``, ``angle``, and
    optionally ``platform`` and ``roas`` keys.

    Parameters
    ----------
    history:
        List of execution result dicts.

    Returns
    -------
    list[str]
        Insight strings describing recurring patterns (e.g.
        ``"satisfaction works well in US"``).
    """
    insights: list[str] = []
    for h in history:
        geo = h.get("geo", "")
        angle = h.get("angle", "")
        roas = h.get("roas", 0.0)
        platform = h.get("platform", "")

        if geo and angle and roas >= 1.5:
            msg = f"{angle} works well in {geo}"
            if platform:
                msg += f" on {platform}"
            if msg not in insights:
                insights.append(msg)

    return insights
