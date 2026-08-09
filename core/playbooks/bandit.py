"""core.playbooks.bandit — epsilon-greedy playbook bandit."""
from __future__ import annotations

import random
from typing import Any

from core.playbooks.selector import select

DEFAULT_EPSILON = 0.2


def choose(
    playbooks: list[dict[str, Any]],
    geo: str = "",
    platform: str = "",
    epsilon: float = DEFAULT_EPSILON,
) -> dict[str, Any]:
    """Return a playbook using epsilon-greedy exploration.

    With probability *epsilon* a random playbook is chosen (exploration);
    otherwise the highest-scoring playbook for *geo*/*platform* is returned
    (exploitation).

    Parameters
    ----------
    playbooks:
        List of playbook dicts each containing at least an ``"id"`` key.
    geo:
        Geo/market context forwarded to :func:`~core.playbooks.selector.select`.
    platform:
        Platform context forwarded to :func:`~core.playbooks.selector.select`.
    epsilon:
        Exploration probability in ``[0, 1]``.

    Returns
    -------
    dict
        The chosen playbook.
    """
    if not playbooks:
        raise ValueError("playbooks list must not be empty")

    if random.random() < epsilon:
        return random.choice(playbooks)
    return select(playbooks, geo=geo, platform=platform)
