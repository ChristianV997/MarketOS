"""core.selection.select — select the best candidate by predicted ROAS."""
from __future__ import annotations

from typing import Any

_MIN_ROAS = 1.8  # Minimum predicted ROAS to justify ad spend (ensures ~80% profit margin after costs)


def select_best(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the candidate with the highest ``predicted_roas``.

    Parameters
    ----------
    candidates:
        List of candidate dicts each containing a ``predicted_roas`` key.

    Returns
    -------
    dict or None
        Best candidate dict, or ``None`` when *candidates* is empty.
    """
    if not candidates:
        return None
    return max(candidates, key=lambda x: float(x.get("predicted_roas", 0)))


def select_viable(
    candidates: list[dict[str, Any]], min_roas: float = _MIN_ROAS
) -> list[dict[str, Any]]:
    """Return candidates whose ``predicted_roas`` meets *min_roas*.

    Parameters
    ----------
    candidates:
        List of candidate dicts.
    min_roas:
        Minimum predicted ROAS threshold for viability (default 1.8).

    Returns
    -------
    list[dict]
        Filtered list, sorted by descending predicted ROAS.
    """
    viable = [c for c in candidates if float(c.get("predicted_roas", 0)) >= min_roas]
    return sorted(viable, key=lambda x: float(x.get("predicted_roas", 0)), reverse=True)
