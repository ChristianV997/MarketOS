"""core.capital.allocator — softmax-based capital allocation engine.

Step 54: Capital Allocation Curves

Implements the allocation strategy described in Step 54:

    score   = ROAS * 0.6 + profit * 0.3 - drawdown * 0.1
    budget_i = total_budget * softmax(score_i / temperature)

Hard limits:
    max_frac = 0.35  (35% of total budget per strategy)
    min_frac = 0.05  (5% minimum for active strategies)

Scaling curve:
    ROAS > 2.5  →  +30%
    ROAS > 2.0  →  +20%
    ROAS > 1.5  →  +10%
    ROAS < 1.0  →  -30%
    ROAS < 0.8  →  kill (0%)
"""
from __future__ import annotations

import math
from typing import Any


# Allocation limits
_MIN_FRAC = 0.05
_MAX_FRAC = 0.35


def _compute_score(strategy: dict[str, Any]) -> float:
    """Compute the composite score for a single strategy.

    score = ROAS * 0.6 + profit * 0.3 - drawdown * 0.1
    """
    roas = strategy.get("roas", 0.0)
    profit = strategy.get("profit", 0.0)
    drawdown = strategy.get("drawdown", 0.0)
    return roas * 0.6 + profit * 0.3 - drawdown * 0.1


def _softmax(scores: list[float], temperature: float) -> list[float]:
    """Return softmax probabilities for *scores* (numerically stable)."""
    temp = max(temperature, 1e-8)
    if not scores:
        return []
    # Subtract the max before exponentiating — mathematically identical
    # output, but prevents math.exp overflow when a score/temp is large
    # (e.g. a pod with large cumulative profit).
    scaled = [s / temp for s in scores]
    hi = max(scaled)
    exps = [math.exp(s - hi) for s in scaled]
    total = sum(exps) or 1.0
    return [e / total for e in exps]


def scale_budget(current_budget: float, roas: float) -> float:
    """Apply the ROAS-driven scaling curve to *current_budget*.

    Returns the adjusted budget (may be 0.0 if ROAS < 0.8 triggers a kill).
    """
    if roas > 2.5:
        return current_budget * 1.30
    if roas > 2.0:
        return current_budget * 1.20
    if roas > 1.5:
        return current_budget * 1.10
    if roas < 0.8:
        return 0.0   # kill
    if roas < 1.0:
        return current_budget * 0.70
    return current_budget


def allocate(
    strategies: list[dict[str, Any]],
    total_budget: float,
    temperature: float = 1.0,
) -> list[float]:
    """Allocate *total_budget* across *strategies* using softmax scoring.

    Parameters
    ----------
    strategies:
        List of strategy dicts; each should have keys ``roas``, ``profit``,
        ``drawdown`` (all default to 0.0 if missing).
    total_budget:
        Total capital to distribute.
    temperature:
        Softmax temperature.
        - 1.0 → balanced
        - 0.5 → aggressive (winner-takes-more)
        - 2.0 → conservative

    Returns
    -------
    list[float]
        Per-strategy budget allocations in the same order as *strategies*.
    """
    n = len(strategies)
    if n == 0:
        return []
    if n == 1:
        return [total_budget]

    raw_scores = [_compute_score(s) for s in strategies]
    weights = _softmax(raw_scores, temperature)

    lo = _MIN_FRAC * total_budget
    hi = _MAX_FRAC * total_budget

    # Waterfall clamp: pin strategies that hit a bound, redistribute the
    # remaining budget among free strategies by weight. Preserves ranking
    # (a clamped winner never re-inflates a loser past it) and deploys the
    # full budget whenever n * max_frac >= 1; otherwise the surplus stays
    # undeployed rather than violating the per-strategy cap.
    allocations = [0.0] * n
    fixed: dict[int, float] = {}
    for _ in range(n):
        free = [i for i in range(n) if i not in fixed]
        if not free:
            break
        budget_left = max(0.0, total_budget - sum(fixed.values()))
        weight_sum = sum(weights[i] for i in free) or 1.0
        for i in free:
            allocations[i] = budget_left * weights[i] / weight_sum
        # Pin cap-violators first — they release budget that may lift the
        # low performers above the floor. Only pin floor-violators once no
        # cap violations remain in the pass.
        hi_violators = [i for i in free if allocations[i] > hi]
        if hi_violators:
            for i in hi_violators:
                fixed[i] = hi
            continue
        lo_violators = [i for i in free if allocations[i] < lo]
        if not lo_violators:
            break
        for i in lo_violators:
            fixed[i] = lo
    for i, v in fixed.items():
        allocations[i] = v

    return allocations
