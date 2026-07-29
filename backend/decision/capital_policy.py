"""backend.decision.capital_policy — the single sanctioned capital allocator.

Before this module the codebase had four disconnected allocation
mechanisms: the CVXPY LP in budget_allocator.py (live, per-cycle variant
budgets), the linear ROAS-share in core/portfolio.py (live, product-level
weights), and two orphans (agents/campaign_budget.py's ±10% ratchet,
agents/allocator.py's mean-reward share) with no production call sites.
Each embodied a different, uncoordinated philosophy of risk.

This module unifies them behind one policy:

    maximize  (pred - λ_eff·width)ᵀ x  −  λ_cov · xᵀ Σ x
    s.t.      Σx = B,   min_frac·B ≤ x_i ≤ max_frac·B

a mean-variance QP — the direct upgrade of the existing LP (the linear
term is identical) with a covariance penalty the LP couldn't express:

  Σ is block-correlated by ``group`` (platform / variant family): arms in
  the same group get correlation ρ, so pouring budget into five TikTok
  arms is priced as one concentrated bet, not five diversified ones.

Adaptive parameters replace the LP's hardcoded constants:

  λ_eff    = λ0 · (1 + drawdown_frac / max_drawdown)  — risk aversion
             tightens automatically as realized drawdown deepens.
  max_frac = clip(2/n, 0.25, 0.60)   — concentration ceiling falls as the
  min_frac = clip(0.5/n, 0.01, 0.05)   portfolio grows; n=2 behaves like
             the old 60% cap, n=8 caps any single arm at 25%.

Shadow mode (CAPITAL_POLICY_LIVE, default false): consumers call
``allocate_with_shadow(...)`` which always computes both the legacy and
policy allocations, journals them side-by-side to the orchestration event
store as a ``shadow_capital_policy`` event, and returns the legacy result
until the flag flips — so no real budget moves on the new math before its
shadow log clears the validation bar.

Solver ladder: CLARABEL (QP) → OSQP (QP) → legacy LP with Σ dropped →
uniform. Never raises.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from backend.risk.config import BASE_MAX_DRAWDOWN

logger = logging.getLogger(__name__)

DEFAULT_RISK_LAMBDA = 0.3     # λ0 — matches the legacy LP's constant
DEFAULT_COV_LAMBDA = 0.15     # weight of the covariance (concentration) penalty
DEFAULT_GROUP_RHO = 0.5       # correlation between arms sharing a group
DEFAULT_WIDTH = 0.5           # uncertainty for arms with no width estimate
DEFAULT_MAX_DRAWDOWN = BASE_MAX_DRAWDOWN   # single-sourced (Phase 5): backend/risk/config.py


def _policy_live() -> bool:
    return os.getenv("CAPITAL_POLICY_LIVE", "false").lower() == "true"


@dataclass
class CapitalAllocation:
    budgets: list[float]                  # same order as input arms
    method: str                           # "qp" | "lp_fallback" | "uniform" | "single"
    lambda_eff: float
    min_frac: float
    max_frac: float
    live: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "budgets": [round(b, 4) for b in self.budgets],
            "method": self.method,
            "lambda_eff": round(self.lambda_eff, 4),
            "min_frac": round(self.min_frac, 4),
            "max_frac": round(self.max_frac, 4),
            "live": self.live,
        }


# ── adaptive parameters ──────────────────────────────────────────────────────

def adaptive_fracs(n: int) -> tuple[float, float]:
    """(min_frac, max_frac) scaled to portfolio size."""
    if n <= 1:
        return 0.0, 1.0
    max_frac = float(np.clip(2.0 / n, 0.25, 0.60))
    min_frac = float(np.clip(0.5 / n, 0.01, 0.05))
    return min_frac, max_frac


def effective_lambda(risk_context: dict | None,
                     base_lambda: float = DEFAULT_RISK_LAMBDA,
                     max_drawdown: float = DEFAULT_MAX_DRAWDOWN) -> float:
    """λ0 scaled up by realized drawdown; λ0 when context is absent."""
    if not risk_context:
        return base_lambda
    capital = float(risk_context.get("capital", 0.0))
    peak = float(risk_context.get("peak_capital", capital))
    if peak <= 0 or capital >= peak:
        return base_lambda
    drawdown_frac = (peak - capital) / peak
    return base_lambda * (1.0 + drawdown_frac / max_drawdown)


def _covariance(widths: np.ndarray, groups: list[str],
                rho: float = DEFAULT_GROUP_RHO) -> np.ndarray:
    """Block-correlation covariance: same group → ρ, else 0; scaled by widths."""
    n = len(widths)
    corr = np.eye(n)
    for i in range(n):
        for j in range(i + 1, n):
            if groups[i] and groups[i] == groups[j]:
                corr[i, j] = corr[j, i] = rho
    sigma = np.outer(widths, widths) * corr
    # symmetric PSD guard: correlation matrix with ρ<1 blocks is PSD, but
    # numeric noise can nudge eigenvalues; project up if needed.
    min_eig = float(np.min(np.linalg.eigvalsh(sigma))) if n > 1 else 0.0
    if min_eig < 0:
        sigma += np.eye(n) * (-min_eig + 1e-9)
    return sigma


# ── core solve ───────────────────────────────────────────────────────────────

def allocate_capital(
    arms: list[dict],
    total_budget: float,
    risk_context: dict | None = None,
    base_lambda: float = DEFAULT_RISK_LAMBDA,
    cov_lambda: float = DEFAULT_COV_LAMBDA,
    group_rho: float = DEFAULT_GROUP_RHO,
) -> CapitalAllocation:
    """Allocate total_budget across arms; never raises.

    Each arm: {id, pred, pred_width (optional), group (optional)}.
    """
    n = len(arms)
    lam = effective_lambda(risk_context, base_lambda)
    min_frac, max_frac = adaptive_fracs(n)

    if n == 0:
        return CapitalAllocation([], "uniform", lam, 0.0, 0.0)
    if n == 1:
        return CapitalAllocation([total_budget], "single", lam, 0.0, 1.0)

    preds = np.array([float(a.get("pred", 1.0)) for a in arms])
    widths = np.array([float(a.get("pred_width", DEFAULT_WIDTH)) for a in arms])
    groups = [str(a.get("group", "") or "") for a in arms]

    coeff = preds - lam * widths
    lo, hi = min_frac * total_budget, max_frac * total_budget

    if np.all(coeff <= 0):
        return CapitalAllocation([total_budget / n] * n, "uniform",
                                 lam, min_frac, max_frac)

    budgets = _solve_qp(coeff, widths, groups, total_budget, lo, hi,
                        cov_lambda, group_rho)
    if budgets is not None:
        return CapitalAllocation(budgets, "qp", lam, min_frac, max_frac)

    # QP solvers unavailable/failed → legacy LP (Σ dropped)
    try:
        from backend.decision.budget_allocator import allocate as lp_allocate
        budgets = lp_allocate(
            [{"pred": p, "pred_width": w} for p, w in zip(preds, widths)],
            total_budget=total_budget, min_frac=min_frac, max_frac=max_frac,
            risk_lambda=lam)
        return CapitalAllocation(list(budgets), "lp_fallback",
                                 lam, min_frac, max_frac)
    except Exception:
        logger.warning("capital_policy_lp_fallback_failed; uniform split")
        return CapitalAllocation([total_budget / n] * n, "uniform",
                                 lam, min_frac, max_frac)


def _solve_qp(coeff: np.ndarray, widths: np.ndarray, groups: list[str],
              total_budget: float, lo: float, hi: float,
              cov_lambda: float, group_rho: float) -> list[float] | None:
    try:
        import cvxpy as cp
    except ImportError:
        return None

    n = len(coeff)
    sigma = _covariance(widths, groups, group_rho)
    x = cp.Variable(n, nonneg=True)
    objective = cp.Maximize(coeff @ x - cov_lambda * cp.quad_form(x, cp.psd_wrap(sigma)))
    constraints = [cp.sum(x) == total_budget, x >= lo, x <= hi]
    prob = cp.Problem(objective, constraints)

    for solver in ("CLARABEL", "OSQP"):
        try:
            prob.solve(solver=solver)
        except Exception:
            continue
        if prob.status in ("optimal", "optimal_inaccurate") and x.value is not None:
            budgets = np.clip(x.value, lo, hi)
            total = float(np.sum(budgets))
            if total <= 0:
                return None
            return list(budgets * total_budget / total)
    return None


# ── shadow-mode wrapper ──────────────────────────────────────────────────────

def allocate_with_shadow(
    arms: list[dict],
    total_budget: float,
    legacy_fn: Callable[[], list[float]],
    risk_context: dict | None = None,
    context_label: str = "",
) -> list[float]:
    """Run legacy and policy allocations side by side.

    Returns the legacy result until CAPITAL_POLICY_LIVE=true; either way
    both vectors are journaled as one shadow_capital_policy event so the
    shadow log accumulates the old-vs-new comparison the validation bar
    needs. Journaling failures never affect the returned allocation.
    """
    live = _policy_live()

    try:
        legacy = list(legacy_fn())
    except Exception:
        logger.exception("legacy_allocator_failed; policy takes over")
        legacy = None

    policy = allocate_capital(arms, total_budget, risk_context=risk_context)
    policy.live = live

    try:
        from backend.orchestration.event_store import event_store, new_workflow_id
        event_store.append(
            new_workflow_id("capalloc"), "shadow_capital_policy",
            workflow="capital_policy", step=context_label or "allocate",
            data={
                "arms": [{"id": a.get("id", ""), "pred": a.get("pred"),
                          "pred_width": a.get("pred_width"),
                          "group": a.get("group", "")} for a in arms],
                "total_budget": total_budget,
                "legacy_budgets": [round(b, 4) for b in legacy] if legacy else None,
                "policy": policy.to_dict(),
            })
    except Exception:
        logger.debug("shadow_capital_policy_journal_failed", exc_info=True)

    if live or legacy is None:
        return policy.budgets
    return legacy


__all__ = [
    "CapitalAllocation", "allocate_capital", "allocate_with_shadow",
    "adaptive_fracs", "effective_lambda",
]
