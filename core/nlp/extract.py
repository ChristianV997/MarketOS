"""core.nlp.extract — text cleaning utilities."""
from __future__ import annotations

import re


def clean_text(text: str) -> str:
    """Lowercase and strip non-alphanumeric characters from *text*.

    Parameters
    ----------
    text:
        Raw text string.

    Returns
    -------
    str
        Cleaned, normalised text.
    """
    text = text.lower()
    text = re.sub(r"[^a-z0-9 ]", "", text)
    return text.strip()
