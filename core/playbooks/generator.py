"""core.playbooks.generator — generate reusable playbooks from winning campaigns."""
from __future__ import annotations

from typing import Any

_DEFAULT_RULES = [
    "use fast pacing",
    "visual proof first",
    "loop ending",
]


def generate_playbook(winner: dict[str, Any]) -> dict[str, Any]:
    """Create a reusable playbook from a winning campaign result.

    Parameters
    ----------
    winner:
        Campaign result dict containing ``niche``, ``angle``, ``hook``, and
        optionally ``format`` keys.

    Returns
    -------
    dict
        Playbook dict with ``niche``, ``angle``, ``hook``, ``format``, and
        ``rules``.
    """
    return {
        "niche": winner.get("niche", ""),
        "angle": winner.get("angle", ""),
        "hook": winner.get("hook", ""),
        "format": winner.get("format", "demo"),
        "rules": list(_DEFAULT_RULES),
    }
