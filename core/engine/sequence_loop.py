"""core.engine.sequence_loop — accumulates per-step transitions into trajectories.

Step 59: Multi-Step RL

Each call to ``step()`` appends a transition to the in-progress trajectory.
When ``flush()`` is called (or the trajectory reaches *max_len* steps) the
full trajectory is pushed to a :class:`~core.rl.trajectory_buffer.TrajectoryBuffer`.
"""
from __future__ import annotations

from typing import Any

from core.rl.trajectory_buffer import TrajectoryBuffer


class SequenceLoop:
    """Accumulate individual step transitions and push complete trajectories.

    Parameters
    ----------
    buffer:
        :class:`TrajectoryBuffer` that receives completed trajectories.
    max_len:
        Maximum number of steps before the trajectory is auto-flushed.
    """

    def __init__(
        self, buffer: TrajectoryBuffer | None = None, max_len: int = 64
    ) -> None:
        self.buffer = buffer or TrajectoryBuffer()
        self.max_len = max_len
        self._current: list[dict[str, Any]] = []

    def step(
        self, state: dict[str, Any], action: str, reward: float
    ) -> None:
        """Record a single transition.

        Auto-flushes the trajectory when it reaches *max_len* steps.
        """
        self._current.append({"state": state, "action": action, "reward": reward})
        if len(self._current) >= self.max_len:
            self.flush()

    def flush(self) -> None:
        """Push the current trajectory to the buffer and start a new one."""
        if self._current:
            self.buffer.push(self._current)
            self._current = []

    @property
    def pending(self) -> int:
        """Number of uncommitted steps in the current trajectory."""
        return len(self._current)
