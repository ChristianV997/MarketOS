"""core.playbooks.selector — context-aware playbook selection."""
from __future__ import annotations

from typing import Any

from core.playbooks.performance import get_avg

_EXPLORATION_SCORE = 0.5


def select(playbooks: list[dict[str, Any]], geo: str, platform: str) -> dict[str, Any]:
    """Return the highest-scoring playbook for the given geo/platform context.

    Each playbook is scored as ``ROAS * 0.7 + CTR * 0.3``.  Playbooks with no
    performance history receive an exploration score of ``0.5``.

    Parameters
    ----------
    playbooks:
        List of playbook dicts each containing at least an ``"id"`` key.
    geo:
        Geo/market context (e.g. ``"US"``).
    platform:
        Execution platform (e.g. ``"tiktok"``).

    Returns
    -------
    dict
        The best-scoring playbook dict.

    Raises
    ------
    ValueError
        If *playbooks* is empty.
    """
    if not playbooks:
        raise ValueError("playbooks list must not be empty")

    scored: list[tuple[dict[str, Any], float]] = []
    for p in playbooks:
        perf = get_avg(p["id"], geo, platform)
        if perf:
            score = perf["roas"] * 0.7 + perf["ctr"] * 0.3
        else:
            score = _EXPLORATION_SCORE
        scored.append((p, score))

    return sorted(scored, key=lambda x: x[1], reverse=True)[0][0]
