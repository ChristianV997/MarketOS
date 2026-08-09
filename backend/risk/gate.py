"""backend.risk.gate — the one choke point real ad spend passes through
before it reaches a platform API.

Before this module, GlobalRiskEngine (core/risk/global_risk_engine.py) had
a real kill switch, daily-spend cap, and drawdown check — but nothing in
the money-spending path ever called record_spend() (so today_spend() was
permanently 0.0 and the cap could never fire) or enforce() (so
POST /risk/kill_switch had no effect on anything that actually spends).

Call check_spend(amount) before any real (non-dry-run) campaign
create/scale call; if not allowed, skip the call entirely rather than
hitting the platform API. Call record_spend(amount) once that call
actually succeeds, so today_spend() reflects reality. Both are no-ops-safe
to call unconditionally — check_spend defaults to "allowed" and
record_spend on a non-positive amount is a no-op — but callers should only
invoke them on the LIVE branch (dry-run spend is not real spend and must
never be recorded).
"""
from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger(__name__)


def _engine():
    from core.risk.global_risk_engine import global_risk_engine
    return global_risk_engine


def _capital_context() -> tuple[float, float]:
    """(current_capital, peak_capital) from the shared system state.

    Falls back to (0.0, 0.0) when the API process's state isn't reachable
    (e.g. a standalone script) — enforce() treats that as "no drawdown
    signal" rather than raising, so the gate degrades to daily-cap/kill-switch
    only rather than failing spend checks outright.
    """
    try:
        from backend.api import _state, _current_peak_capital
        return float(_state.capital), float(_current_peak_capital())
    except Exception:
        return 0.0, 0.0


def check_spend(proposed_amount: float) -> dict[str, Any]:
    """Gate a proposed real-money spend against the kill switch, drawdown,
    and daily-spend cap. Returns {allowed, adjusted_amount, reason,
    triggered_cap} — adjusted_amount may be lower than proposed_amount if
    it was capped down to what's left of the daily budget."""
    engine = _engine()
    current_capital, peak_capital = _capital_context()
    override = engine.enforce(
        proposed_budget=proposed_amount,
        current_capital=current_capital,
        peak_capital=peak_capital,
    )
    if not override.allowed or override.adjusted_budget < proposed_amount:
        _log.warning("risk_gate proposed=%.2f allowed=%s adjusted=%.2f reason=%s",
                    proposed_amount, override.allowed, override.adjusted_budget,
                    override.reason)
    return {
        "allowed": override.allowed,
        "adjusted_amount": override.adjusted_budget,
        "reason": override.reason,
        "triggered_cap": override.triggered_cap,
    }


def record_spend(amount: float) -> None:
    """Record real (non-dry-run) spend that actually went live. No-op for
    non-positive amounts (a paused/killed campaign frees budget, it
    doesn't spend more)."""
    if amount <= 0:
        return
    _engine().record_spend(amount)
