"""api.routes.agents_risk — agent hierarchy performance panel + global risk engine controls."""
from __future__ import annotations

from fastapi import APIRouter

from agents.arbitration import arbitrate
from backend import api as _core
from backend.execution.loop import TOTAL_CYCLE_BUDGET

router = APIRouter()


@router.get("/agents")
def agent_performance():
    """Agent performance panel: decisions, PnL, drift detection, and the
    arbitrated outcome (see agents.arbitration) of the four agents' input
    for the latest window."""
    state = _core._state
    rows = state.event_log.rows
    recent = rows[-_core._RECENT_ROWS_WINDOW:] if rows else []

    arbitrated = None
    if recent:
        avg_roas = sum(r.get("roas", 0) for r in recent) / len(recent)
        avg_ctr = sum(r.get("ctr", 0) for r in recent) / len(recent)
        avg_cvr = sum(r.get("cvr", 0) for r in recent) / len(recent)

        scaling_dec = _core._scaling_agent.decide({"roas": avg_roas, "current_budget": TOTAL_CYCLE_BUDGET})
        geo_dec = _core._geo_agent.decide({"country": "system", "roas": avg_roas})
        audience_dec = _core._audience_agent.decide({"ctr": avg_ctr, "cvr": avg_cvr})
        risk_input = {
            "current_capital": state.capital,
            "peak_capital": _core._current_peak_capital(),
            "today_spend": _core._global_risk_engine.today_spend(),
            "roas": avg_roas,
            "kill_switch": _core._global_risk_engine.kill_switch_active,
        }
        risk_dec = _core._risk_agent.decide(risk_input)

        decisions = [scaling_dec, geo_dec, audience_dec, risk_dec]
        for dec in decisions:
            _core._agent_metrics.record_decision(dec.agent, dec.action)

        arbitrated = arbitrate(decisions).to_dict()

    return {
        "agents": _core._agent_metrics.snapshot(),
        "risk_status": _core._global_risk_engine.status(),
        "arbitrated_decision": arbitrated,
    }


@router.get("/risk/status")
def risk_engine_status():
    """Global risk engine status: kill-switch, daily spend, drawdown caps."""
    return _core._global_risk_engine.status()


@router.post("/risk/killswitch/activate")
def activate_kill_switch(reason: str = "manual"):
    """Activate the global kill-switch — halts all new spend immediately."""
    _core._global_risk_engine.activate_kill_switch(reason=reason)
    return {"kill_switch_active": True, "reason": reason}


@router.post("/risk/killswitch/deactivate")
def deactivate_kill_switch():
    """Deactivate the global kill-switch — resumes normal operation."""
    _core._global_risk_engine.deactivate_kill_switch()
    return {"kill_switch_active": False}


__all__ = ["router"]
