"""core.rl.returns — discounted return computation for trajectory batches."""
from __future__ import annotations


def discounted_returns(rewards: list[float], gamma: float = 0.99) -> list[float]:
    """Compute discounted returns for a sequence of rewards.

    Parameters
    ----------
    rewards:
        Ordered list of scalar rewards from a single trajectory.
    gamma:
        Discount factor (default 0.99).

    Returns
    -------
    list[float]
        G_t = r_t + gamma * r_{t+1} + gamma^2 * r_{t+2} + ... for each step.
    """
    returns: list[float] = []
    running = 0.0
    for r in reversed(rewards):
        running = r + gamma * running
        returns.append(running)
    returns.reverse()
    return returns


def trajectory_returns(
    trajectory: list[dict], gamma: float = 0.99
) -> list[dict]:
    """Annotate each transition in *trajectory* with its discounted return.

    Parameters
    ----------
    trajectory:
        List of ``{"state": ..., "action": ..., "reward": float, ...}`` dicts.
    gamma:
        Discount factor.

    Returns
    -------
    list[dict]
        Same transitions with an added ``"return"`` key.
    """
    rewards = [float(t.get("reward", 0.0)) for t in trajectory]
    rets = discounted_returns(rewards, gamma)
    return [{**t, "return": g} for t, g in zip(trajectory, rets)]
