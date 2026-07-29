"""
CVXPY risk-adjusted budget allocator.

Problem (LP):
    maximize  sum_i ( pred_i - risk_lambda * width_i ) * x_i
    subject to
        sum_i x_i  = total_budget
        min_frac * total_budget <= x_i <= max_frac * total_budget   for all i

Where:
  pred_i    = calibration-adjusted ROAS prediction for decision i
  width_i   = MAPIE interval width (uncertainty proxy) for decision i
  x_i       = budget allocated to decision i (optimisation variable)
  risk_lambda = trades off expected return vs. uncertainty penalisation

Fallback: if CVXPY fails or the problem is infeasible, returns uniform split.
Solvers tried in order: HiGHS (LP-optimised), CLARABEL, uniform split.
"""
import logging

import numpy as np

try:  # CVXPY is an optional accelerator, not a runtime requirement.
    import cvxpy as cp
except ImportError:  # pragma: no cover - exercised in minimal deployments
    cp = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Default parameters — overridable per call
DEFAULT_TOTAL_BUDGET = 500.0   # total spend per cycle (5 decisions × $100 baseline)
DEFAULT_MIN_FRAC = 0.05        # each arm gets at least 5% of budget
DEFAULT_MAX_FRAC = 0.60        # no single arm gets more than 60%
DEFAULT_RISK_LAMBDA = 0.3      # uncertainty penalty weight


def _bounded_greedy_allocation(coeff: np.ndarray, *, total_budget: float, lo: float, hi: float) -> list[float]:
    """Solve this simple bounded linear allocation without an LP dependency.

    The optimum of a linear objective under box constraints is obtained by
    assigning the remaining budget to the highest-value arms first.  This
    provides the same risk ordering as the CVXPY path and keeps the execution
    loop functional in small or Python-version-leading deployments.
    """
    n = len(coeff)
    if n == 0:
        return []
    if n * lo > total_budget or n * hi < total_budget:
        logger.warning("infeasible allocation bounds; using uniform allocation")
        return [total_budget / n] * n

    budgets = np.full(n, lo, dtype=float)
    remaining = total_budget - float(budgets.sum())
    for index in np.argsort(-coeff, kind="stable"):
        addition = min(remaining, hi - budgets[index])
        budgets[index] += addition
        remaining -= addition
        if remaining <= 1e-9:
            break
    return [float(value) for value in budgets]


def allocate(
    decisions: list[dict],
    total_budget: float = DEFAULT_TOTAL_BUDGET,
    min_frac: float = DEFAULT_MIN_FRAC,
    max_frac: float = DEFAULT_MAX_FRAC,
    risk_lambda: float = DEFAULT_RISK_LAMBDA,
) -> list[float]:
    """
    Returns a list of per-decision budget allocations (same order as decisions).

    decisions: list of decision dicts, each with keys:
        pred       — calibrated ROAS point estimate
        pred_width — MAPIE interval width (optional, defaults to 0.5)
    """
    n = len(decisions)
    if n == 0:
        return []
    if n == 1:
        return [total_budget]

    preds = np.array([d.get("pred", 1.0) for d in decisions], dtype=float)
    widths = np.array([d.get("pred_width", 0.5) for d in decisions], dtype=float)

    # risk-adjusted expected value coefficients
    coeff = preds - risk_lambda * widths

    lo = min_frac * total_budget
    hi = max_frac * total_budget

    # guard: if all coefficients are non-positive, fall back to uniform
    if np.all(coeff <= 0):
        return [total_budget / n] * n

    # Keep production behaviour when the optional solver is available, but
    # preserve a deterministic optimizer when it is not.
    if cp is None:
        return _bounded_greedy_allocation(coeff, total_budget=total_budget, lo=lo, hi=hi)

    x = cp.Variable(n, nonneg=True)

    objective = cp.Maximize(coeff @ x)
    constraints = [
        cp.sum(x) == total_budget,
        x >= lo,
        x <= hi,
    ]

    prob = cp.Problem(objective, constraints)
    try:
        prob.solve(solver=cp.HIGHS)
    except (cp.SolverError, Exception):
        try:
            prob.solve(solver=cp.CLARABEL)
        except (cp.SolverError, Exception):
            logger.warning("CVXPY solver failed; using deterministic bounded allocation")
            return _bounded_greedy_allocation(coeff, total_budget=total_budget, lo=lo, hi=hi)

    if prob.status not in (cp.OPTIMAL, cp.OPTIMAL_INACCURATE) or x.value is None:
        return _bounded_greedy_allocation(coeff, total_budget=total_budget, lo=lo, hi=hi)

    budgets = list(np.clip(x.value, lo, hi))
    # re-normalise to exact total (floating-point residual)
    total = sum(budgets)
    return [b * total_budget / total for b in budgets]


def allocation_summary(decisions: list[dict], budgets: list[float]) -> str:
    """Human-readable one-line summary for logging."""
    parts = [
        f"v{d['action'].get('variant','?')}=${b:.0f}(pred={d.get('pred',0):.3f}±{d.get('pred_width',0):.3f})"
        for d, b in zip(decisions, budgets)
    ]
    return "budget: " + "  ".join(parts)
