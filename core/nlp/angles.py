"""core.nlp.angles — keyword-based content angle extraction."""
from __future__ import annotations

KEYWORDS: dict[str, list[str]] = {
    "problem": ["fix", "problem", "issue"],
    "convenience": ["easy", "fast", "quick"],
    "satisfaction": ["satisfying", "clean", "perfect"],
    "transformation": ["before", "after", "change"],
}


def extract_angles(text: str) -> list[str]:
    """Return a list of content angles detected in *text*.

    Parameters
    ----------
    text:
        Cleaned lower-case text string.

    Returns
    -------
    list[str]
        Deduplicated list of angle labels (e.g. ``["problem", "satisfaction"]``).
    """
    found = []
    for angle, words in KEYWORDS.items():
        for w in words:
            if w in text:
                found.append(angle)
                break
    return list(set(found))
