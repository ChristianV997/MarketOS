"""core.rl.reward — strategy-level reward combining profit, drawdown, stability."""
from __future__ import annotations


def compute_reward(
    profit: float,
    drawdown: float,
    stability: float = 0.0,
    profit_w: float = 0.6,
    drawdown_w: float = 0.3,
    stability_w: float = 0.1,
) -> float:
    """Combine profit, drawdown penalty, and stability bonus into a scalar reward.

    Parameters
    ----------
    profit:
        Realised profit (positive is good).
    drawdown:
        Current drawdown magnitude (positive value → penalty).
    stability:
        Measure of volatility stability (higher is better).
    profit_w, drawdown_w, stability_w:
        Weights for each component (should sum to 1).

    Returns
    -------
    float
        Weighted reward scalar.
    """
    return profit_w * profit - drawdown_w * drawdown + stability_w * stability


def reward_from_state(state: dict) -> float:
    """Extract reward from a state dict using standard field names.

    Parameters
    ----------
    state:
        Dict expected to contain ``profit``, ``drawdown``, and optionally
        ``stability``.

    Returns
    -------
    float
        Computed reward.
    """
    profit = float(state.get("profit", 0.0))
    drawdown = float(state.get("drawdown", 0.0))
    stability = float(state.get("stability", 0.0))
    return compute_reward(profit, drawdown, stability)
