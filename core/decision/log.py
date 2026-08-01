"""core.decision.log — decision logging with WHY + expected outcome."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

_DECISIONS: list[dict[str, Any]] = []


def log_decision(
    input_data: Any,
    decision: str,
    reason: str | list[str],
    expected_outcome: str,
) -> dict[str, Any]:
    """Record a system decision with its rationale and expected outcome.

    Parameters
    ----------
    input_data:
        The signals or state that triggered the decision.
    decision:
        Short description of the action taken (e.g. ``"Scale Creative A"``).
    reason:
        Human-readable explanation string or list of reasons.
    expected_outcome:
        Description of the expected result.

    Returns
    -------
    dict
        The logged entry (also appended to the module-level store).
    """
    entry: dict[str, Any] = {
        "time": datetime.now(tz=timezone.utc).isoformat(),
        "input": input_data,
        "decision": decision,
        "reason": reason if isinstance(reason, list) else [reason],
        "expected": expected_outcome,
    }
    _DECISIONS.append(entry)
    return entry


def get_all() -> list[dict[str, Any]]:
    """Return all logged decisions."""
    return list(_DECISIONS)


def clear() -> None:
    """Clear the decision log (useful in tests)."""
    _DECISIONS.clear()
