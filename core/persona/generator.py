"""core.persona.generator — generate audience personas from cluster data."""
from __future__ import annotations

from typing import Any


def generate_persona(cluster: list[dict[str, Any]], angles: list[str]) -> dict[str, Any]:
    """Return an audience persona derived from cluster characteristics.

    Parameters
    ----------
    cluster:
        List of signal dicts (reserved for future demographic inference).
    angles:
        Content angles detected in the cluster (used as pain-point proxies).

    Returns
    -------
    dict
        Persona with ``age_range``, ``interests``, ``pain_points``, and
        ``platform`` keys.
    """
    return {
        "age_range": "18-34",
        "interests": ["convenience", "lifestyle"],
        "pain_points": list(angles),
        "platform": "TikTok",
    }
