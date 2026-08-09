"""discovery.clustering — group signals into niche clusters."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

_NICHE_KEYWORDS: dict[str, list[str]] = {
    "cleaning": ["clean", "scrub", "wash", "sanitize", "mop"],
    "kitchen": ["kitchen", "blend", "cook", "chef", "recipe", "food"],
    "fitness": ["gym", "workout", "fitness", "exercise", "lift", "run"],
    "beauty": ["beauty", "skincare", "makeup", "glow", "moistur"],
    "tech": ["tech", "gadget", "app", "phone", "laptop", "device"],
}


def extract_niche(text: str) -> str:
    """Return a niche label for *text* based on keyword matching.

    Falls back to ``"general"`` when no keyword matches.
    """
    lower = text.lower()
    for niche, keywords in _NICHE_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return niche
    return "general"


def cluster(signals: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group *signals* by extracted niche.

    Parameters
    ----------
    signals:
        List of signal dicts containing at least a ``"text"`` key.

    Returns
    -------
    dict[str, list]
        Mapping of niche label → list of signal dicts belonging to that niche.
    """
    clusters: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in signals:
        key = extract_niche(s.get("text", ""))
        clusters[key].append(s)
    return dict(clusters)
