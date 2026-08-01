"""core.world_model.planner — simulate future trajectories via a world model."""
from __future__ import annotations

from typing import Any, Callable

from core.world_model.model import WorldModel


def simulate(
    model: WorldModel,
    state: dict[str, Any],
    policy: Callable[[dict[str, Any]], str],
    horizon: int = 5,
) -> list[tuple[dict[str, Any], str]]:
    """Roll out a trajectory by repeatedly querying *policy* and *model*.

    Parameters
    ----------
    model:
        :class:`WorldModel` used to predict the next state.
    state:
        Starting state dict.
    policy:
        Callable ``(state) -> action_str``.
    horizon:
        Number of simulation steps.

    Returns
    -------
    list[tuple[dict, str]]
        Sequence of ``(predicted_state, action)`` pairs.
    """
    traj: list[tuple[dict[str, Any], str]] = []
    s = state
    for _ in range(horizon):
        a = policy(s)
        s = model.predict_next(s, a)
        traj.append((s, a))
    return traj
