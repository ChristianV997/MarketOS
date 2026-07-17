"""api.routes.decisions — ranked decisions, budget allocation, risk-adjusted capital."""
from __future__ import annotations

from fastapi import APIRouter, Query

from backend import api as _core
from backend.decision.engine import decide
from backend.decision.budget_allocator import allocate as budget_allocate

router = APIRouter()


@router.get("/decisions")
def decisions():
    """Top 5 ranked decisions with full prediction detail and human-readable reason."""
    state = _core._state
    top = decide(state)[:5]
    budgets = budget_allocate(top)
    result = []
    for i, d in enumerate(top):
        pred = round(d.get("pred", 0), 4)
        pred_width = round(d.get("pred_width") or 0, 4)
        system_conf = round(d.get("system_conf") or 0, 4)
        interval_conf = round(d.get("interval_conf") or 0, 4)
        score = round(d["score"], 4)

        # Build human-readable decision explanation
        if pred >= 2.0 and system_conf >= 0.6 and interval_conf >= 0.6:
            reason = (
                f"Scaled: ROAS {pred} predicted with high confidence "
                f"(system={system_conf}, interval={interval_conf})"
            )
        elif pred < 1.0:
            reason = (
                f"Kill candidate: predicted ROAS {pred} below break-even "
                f"(score={score})"
            )
        elif pred_width > 1.0:
            reason = (
                f"Hold: high prediction uncertainty (width={pred_width}), "
                f"awaiting more data"
            )
        elif pred >= 1.5:
            reason = (
                f"Monitor/Scale: ROAS {pred} above threshold, "
                f"confidence={system_conf}"
            )
        else:
            reason = (
                f"Hold: moderate ROAS {pred}, insufficient confidence "
                f"(score={score})"
            )

        result.append({
            "action":        d["action"],
            "score":         score,
            "pred":          pred,
            "pred_lo":       round(d.get("pred_lo") or 0, 4),
            "pred_hi":       round(d.get("pred_hi") or 0, 4),
            "pred_width":    pred_width,
            "interval_conf": interval_conf,
            "system_conf":   system_conf,
            "budget":        round(budgets[i], 2),
            "reason":        reason,
        })
    return result


@router.get("/budget")
def budget():
    """Latest CVXPY budget allocation across the top 5 decisions."""
    top = decide(_core._state)[:5]
    budgets = budget_allocate(top)
    return [
        {
            "variant": d["action"].get("variant"),
            "budget": round(budgets[i], 2),
            "pred": round(d.get("pred", 0), 4),
            "pred_width": round(d.get("pred_width") or 0, 4),
        }
        for i, d in enumerate(top)
    ]


@router.get("/capital_allocation")
def capital_allocation():
    """Capital allocation view: portfolio split and risk-adjusted budgets."""
    state = _core._state
    top = decide(state)[:5]
    budgets = budget_allocate(top)

    total = sum(budgets) or 1.0
    result = []
    for i, d in enumerate(top):
        raw_budget = budgets[i]
        # enforce through global risk engine
        override = _core._global_risk_engine.enforce(
            proposed_budget=raw_budget,
            current_capital=state.capital,
            peak_capital=_core._current_peak_capital(),
        )
        safe_budget = override.adjusted_budget if override.allowed else 0.0
        result.append({
            "variant": d["action"].get("variant"),
            "raw_budget": round(raw_budget, 2),
            "safe_budget": round(safe_budget, 2),
            "allocation_pct": round(raw_budget / total * 100, 2),
            "risk_override": override.triggered_cap != "" or not override.allowed,
            "risk_reason": override.reason,
            "pred": round(d.get("pred", 0), 4),
        })

    return {
        "total_budget": round(total, 2),
        "risk_status": _core._global_risk_engine.status(),
        "allocations": result,
    }


@router.get("/prediction_errors")
def prediction_errors(limit: int = Query(default=100, ge=1, le=500)):
    """Prediction error chart: recent (predicted, actual, error) pairs with calibration stats."""
    errors = _core._wm_calibrator.prediction_errors()[-limit:]
    stats = _core._wm_calibrator.stats()
    return {
        "errors": errors,
        "calibration": stats,
        "total_updates": _core._wm_calibrator.total_updates,
    }


__all__ = ["router"]
