"""core.sensors.google_trends — fetch trending search terms via pytrends."""
from __future__ import annotations


def fetch_trends(geo: str = "united_states") -> list[str]:
    """Return a list of current trending search terms for *geo*.

    Requires ``pytrends`` to be installed.  Returns an empty list when the
    dependency is missing or the request fails.

    Parameters
    ----------
    geo:
        Country/region name supported by pytrends (e.g. ``"united_states"``).

    Returns
    -------
    list[str]
        Top trending search terms.
    """
    try:
        from pytrends.request import TrendReq  # type: ignore[import]
    except ImportError:
        return []

    try:
        pytrends = TrendReq()
        return pytrends.trending_searches(pn=geo)[0].tolist()
    except Exception:
        return []
