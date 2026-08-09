"""core.world_model.model — nearest-neighbour world model (Dreamer-style stub)."""
from __future__ import annotations

from typing import Any


class WorldModel:
    """Simple world model that stores observed transitions and predicts via
    nearest-neighbour lookup on the action key.

    Parameters
    ----------
    maxlen:
        Maximum number of transitions to keep in memory.
    """

    def __init__(self, maxlen: int = 10_000) -> None:
        self.memory: list[dict[str, Any]] = []
        self._maxlen = maxlen

    def train(self, transitions: list[dict[str, Any]]) -> None:
        """Append *transitions* to internal memory, trimming oldest entries."""
        self.memory.extend(transitions)
        if len(self.memory) > self._maxlen:
            self.memory = self.memory[-self._maxlen:]

    def predict_next(
        self, state: dict[str, Any], action: str
    ) -> dict[str, Any]:
        """Return the most recently seen next-state for *action*.

        Falls back to returning *state* unchanged when no matching transition
        exists.

        Parameters
        ----------
        state:
            Current state (not used by the nearest-neighbour heuristic but
            available for future model upgrades).
        action:
            Proposed action string.

        Returns
        -------
        dict
            Predicted next state.
        """
        for t in reversed(self.memory):
            if t.get("action") == action:
                return t.get("next_state", state)
        return state
