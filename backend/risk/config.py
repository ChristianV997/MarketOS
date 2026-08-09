"""backend.risk.config — single-sourced, adaptive risk constants.

Phase 5 fix: ``agents/hierarchy.py::RiskAgent`` and
``core/risk/global_risk_engine.py::GlobalRiskEngine`` each independently
hardcoded ``max_drawdown=0.30`` / ``max_daily_spend=$10,000`` — the same
business constants defined twice, as static dollar amounts that never
scaled with capital growth or realized volatility. This module is the
single source for both, plus the adaptive formulas that replace the
static behavior once ``RISK_ADAPTIVE_LIVE`` is flipped on.

Design:
  * ``adaptive_max_daily_spend``: scales the spend cap with the ratio of
    current to initial capital (a $10k cap that made sense at $1k starting
    capital is either reckless or needlessly tight once capital has moved
    10x in either direction), then applies an inverse-volatility scale —
    standard vol-targeting risk sizing (position/spend size ∝ 1/volatility
    around a reference level) — so spend leans in during calm markets and
    pulls back during turbulent ones. Bounded so it can never run away in
    either direction.
  * ``adaptive_max_drawdown``: narrows (never widens) the drawdown
    tolerance as portfolio concentration or realized volatility rise above
    baseline — a concentrated bet or an unusually volatile stretch is
    exactly when a given drawdown number is least informative and the
    system should be most willing to cut losses early. The static 0.30 is
    the ceiling (least-restrictive case: zero concentration, at-or-below
    baseline volatility), never the floor.

Both adaptive functions gracefully degrade to their inputs' base value
when optional context (volatility, concentration) is unavailable — the
same "no signal, no adjustment" pattern used throughout this codebase's
shadow-mode phases (e.g. ``backend/decision/capital_policy.py``'s
``effective_lambda``).
"""
from __future__ import annotations

import os

from backend.core.state import DEFAULT_CAPITAL

# ── single-sourced business constants (the pre-Phase-5 hardcoded values) ──
BASE_MAX_DRAWDOWN = 0.30
BASE_MAX_DAILY_SPEND = 10_000.0
DEFAULT_INITIAL_CAPITAL = DEFAULT_CAPITAL

# Reference realized-volatility level used to normalize the vol-scaling
# adjustments below. Chosen to match backend/regime/detector.py's own
# ``volatility > 0.1`` "volatile" classification threshold, reusing an
# implicit scale already established elsewhere in the codebase rather than
# inventing a new arbitrary constant.
BASELINE_VOLATILITY = 0.1

# Hard floors so neither adaptive formula can degenerate to zero/negative.
MIN_MAX_DRAWDOWN = 0.05
MIN_DAILY_SPEND = 100.0

# Bounds on the multiplicative scale factors themselves.
_SPEND_CAPITAL_SCALE_MIN = 0.1
_SPEND_CAPITAL_SCALE_MAX = 5.0
_SPEND_VOL_SCALE_MIN = 0.5
_SPEND_VOL_SCALE_MAX = 1.5
_DRAWDOWN_VOL_FACTOR_MIN = 0.5
_DRAWDOWN_VOL_FACTOR_MAX = 1.0  # drawdown tolerance only ever tightens


def risk_adaptive_live() -> bool:
    return os.getenv("RISK_ADAPTIVE_LIVE", "false").lower() == "true"


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def adaptive_max_daily_spend(
    capital: float,
    initial_capital: float = DEFAULT_INITIAL_CAPITAL,
    volatility: float | None = None,
    base_spend: float = BASE_MAX_DAILY_SPEND,
    baseline_volatility: float = BASELINE_VOLATILITY,
) -> float:
    """Daily spend cap scaled to capital growth and realized volatility.

    ``capital_scale`` grows/shrinks the cap proportionally to how much
    capital is actually under management relative to where the strategy
    started. ``vol_scale`` is an inverse-volatility adjustment (vol-target
    sizing): calmer-than-baseline markets get a modest allowance to lean
    in (capped at 1.5x), more volatile markets pull back (floored at 0.5x).
    """
    capital_scale = capital / max(initial_capital, 1e-6)

    if volatility is None:
        vol_scale = 1.0
    else:
        vol_scale = _clip(
            baseline_volatility / max(volatility, 1e-6),
            _SPEND_VOL_SCALE_MIN, _SPEND_VOL_SCALE_MAX,
        )

    total_scale = _clip(
        capital_scale * vol_scale,
        _SPEND_CAPITAL_SCALE_MIN, _SPEND_CAPITAL_SCALE_MAX,
    )
    return max(base_spend * total_scale, MIN_DAILY_SPEND)


def adaptive_max_drawdown(
    concentration_frac: float = 0.0,
    volatility: float | None = None,
    base_drawdown: float = BASE_MAX_DRAWDOWN,
    baseline_volatility: float = BASELINE_VOLATILITY,
) -> float:
    """Drawdown tolerance narrowed by concentration and excess volatility.

    ``concentration_frac`` is the largest single platform/audience
    bucket's share of total budget (0 = perfectly diversified, 1 = all-in
    on one bet); tolerance scales down linearly with it, since a
    concentrated portfolio is one correlated wager, not several
    independent ones, and should be cut loose sooner. ``volatility``, when
    supplied, can only ever tighten the cap (never loosen it beyond
    ``base_drawdown``) — the static 0.30 remains the least-restrictive
    ceiling.
    """
    concentration_frac = _clip(concentration_frac, 0.0, 1.0)
    concentration_factor = 1.0 - concentration_frac

    if volatility is None:
        vol_factor = 1.0
    else:
        vol_factor = _clip(
            baseline_volatility / max(volatility, 1e-6),
            _DRAWDOWN_VOL_FACTOR_MIN, _DRAWDOWN_VOL_FACTOR_MAX,
        )

    max_dd = base_drawdown * concentration_factor * vol_factor
    return max(max_dd, MIN_MAX_DRAWDOWN)


def concentration_fraction(group_budgets: dict) -> float:
    """Largest single group's share of total budget, in [0, 1].

    A plain utility for callers to derive ``concentration_frac`` from a
    ``{group: budget}`` mapping (e.g. per-platform or per-audience spend)
    before calling ``adaptive_max_drawdown`` — the same correlation-aware
    grouping already used by ``backend/decision/capital_policy.py``'s
    block-correlation covariance term.
    """
    if not group_budgets:
        return 0.0
    total = sum(group_budgets.values())
    if total <= 0:
        return 0.0
    return max(group_budgets.values()) / total
