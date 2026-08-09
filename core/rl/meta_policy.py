"""core.rl.meta_policy — hierarchical meta-policy that selects strategy modes."""
from __future__ import annotations

from typing import Any

_SCALE = "scale"
_EXPLORE = "explore"
_PROTECT = "protect"

STRATEGIES = [_SCALE, _EXPLORE, _PROTECT]


class MetaPolicy:
    """Select a high-level strategy based on the current system state.

    Decision rule:
    - ROAS > 2.5  → **scale** (capitalise on profitable campaigns)
    - ROAS < 1.2  → **protect** (reduce risk / budget)
    - otherwise   → **explore** (test new ideas)
    """

    def select(self, state: dict[str, Any]) -> str:
        """Return one of ``"scale"``, ``"explore"``, or ``"protect"``.

        Parameters
        ----------
        state:
            Dict containing at least a ``"roas"`` key.
        """
        roas = float(state.get("roas", 1.0))
        if roas > 2.5:
            return _SCALE
        if roas < 1.2:
            return _PROTECT
        return _EXPLORE


def worker_policy(state: dict[str, Any], strategy: str) -> str:
    """Map a high-level *strategy* to a concrete worker action.

    Parameters
    ----------
    state:
        Current system state (reserved for future use).
    strategy:
        One of the strategy strings produced by :class:`MetaPolicy`.

    Returns
    -------
    str
        A concrete action string: ``"increase_budget"``, ``"reduce_budget"``,
        or ``"test_new_creative"``.
    """
    if strategy == _SCALE:
        return "increase_budget"
    if strategy == _PROTECT:
        return "reduce_budget"
    return "test_new_creative"
