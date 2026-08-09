"""core.rl.trajectory_buffer — stores sequences of (state, action, reward)."""
from __future__ import annotations

from collections import deque
from typing import Any


class TrajectoryBuffer:
    """Fixed-size buffer that stores complete trajectories.

    Each trajectory is a list of ``{"state": ..., "action": ..., "reward": ...}``
    transition dicts pushed as a unit.
    """

    def __init__(self, maxlen: int = 1000) -> None:
        self._buf: deque[list[dict[str, Any]]] = deque(maxlen=maxlen)

    def push(self, trajectory: list[dict[str, Any]]) -> None:
        """Append a complete trajectory to the buffer."""
        if trajectory:
            self._buf.append(list(trajectory))

    def sample(self, n: int = 8) -> list[list[dict[str, Any]]]:
        """Return up to *n* trajectories (most recent when buffer is small)."""
        items = list(self._buf)
        return items[-n:] if len(items) >= n else items

    def __len__(self) -> int:
        return len(self._buf)
