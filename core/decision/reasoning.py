"""core.decision.reasoning — rule-based decision explanation engine."""
from __future__ import annotations

from typing import Any


def explain(signal: dict[str, Any], metrics: dict[str, Any]) -> list[str]:
    """Generate a list of human-readable reasons for a scaling/action decision.

    Parameters
    ----------
    signal:
        Engagement signal dict (expects an ``"engagement"`` key).
    metrics:
        Campaign performance metrics (expects ``"ctr"`` and ``"roas"`` keys).

    Returns
    -------
    list[str]
        Non-empty list of reason strings.  Falls back to ``["no strong signal"]``
        when none of the threshold conditions are met.
    """
    reasons: list[str] = []

    if float(signal.get("engagement", 0)) > 0.06:
        reasons.append("high engagement")

    if float(metrics.get("ctr", 0)) > 0.015:
        reasons.append("strong CTR")

    if float(metrics.get("roas", 0)) > 2.0:
        reasons.append("profitable")

    return reasons if reasons else ["no strong signal"]
