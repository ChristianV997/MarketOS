"""discovery.angles — extract content angles from a signal text."""
from __future__ import annotations

_ANGLE_KEYWORDS: dict[str, list[str]] = {
    "satisfaction": ["satisfying", "satisf", "oddly", "asmr"],
    "problem-solution": ["fix", "problem", "issue", "broken", "solve", "solution"],
    "transformation": ["before", "transform", "glow", "change", "result"],
    "convenience": ["easy", "quick", "simple", "fast", "effortless"],
    "curiosity": ["weird", "strange", "unexpected", "secret", "hidden"],
}


def extract_angles(signal: dict | str) -> list[str]:
    """Return a list of content angles for the given signal.

    Parameters
    ----------
    signal:
        Either a signal dict (with a ``"text"`` key) or a plain string.

    Returns
    -------
    list[str]
        Matched angle labels (may be empty if no keyword matches).
    """
    text = signal.get("text", "") if isinstance(signal, dict) else str(signal)
    lower = text.lower()
    angles: list[str] = []
    for angle, keywords in _ANGLE_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            angles.append(angle)
    return angles
