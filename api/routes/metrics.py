"""api.routes.metrics — dashboard metrics payload, event log, causal graph, memory."""
from __future__ import annotations

import numpy as np
from fastapi import APIRouter, Query

import backend.learning.calibration as cal
import backend.learning.bandit_update as bu
import backend.regime.confidence as rc
from backend import api as _core
from backend.agents.structural_evolution import structural_engine

router = APIRouter()


@router.get("/metrics")
def metrics():
    """Rich dashboard payload — all key metrics in one call."""
    state = _core._state
    rows = state.event_log.rows
    recent = rows[-100:] if rows else []

    avg_roas = round(sum(r.get("roas", 0) for r in recent) / max(len(recent), 1), 4)
    slope = _core._roas_trend_slope(rows)

    # calibration
    cal_stats = cal.calibration_model.stats()

    # bandit rankings
    bandit_rankings = []
    for action_key, rewards in bu.bandit_memory.history.items():
        if rewards:
            bandit_rankings.append({
                "action": action_key,
                "avg_reward": round(float(np.mean(rewards)), 4),
                "count": len(rewards),
            })
    bandit_rankings.sort(key=lambda x: x["avg_reward"], reverse=True)

    # regime confidence
    reg_conf = round(rc.regime_confidence.confidence(), 4)

    # population diversity
    diversity = (
        round(structural_engine.population_diversity(), 4)
        if structural_engine.population else None
    )

    return {
        "avg_roas": avg_roas,
        "roas_trend_slope": slope,
        "capital": round(state.capital, 2),
        "capital_gain": round(state.capital - 1000.0, 2),
        "detected_regime": state.detected_regime,
        "regime_confidence": reg_conf,
        "calibration": {
            "bias": round(cal_stats.get("bias", 0), 4),
            "uncertainty": round(cal_stats.get("uncertainty", 1), 4),
            "confidence_weight": round(cal.calibration_model.confidence_weight(), 4),
        },
        "variant_performance": _core._variant_avg(recent),
        "bandit_rankings": bandit_rankings[:5],
        "total_cycles": state.total_cycles,
        "causal_edges": len(state.graph.edges),
        "population_diversity": diversity,
        "event_count": len(rows),
        "cac_estimate": _core._cac_estimate(),
    }


@router.get("/events")
def events(limit: int = Query(default=200, ge=1, le=1000)):
    """
    Last `limit` event-log rows for chart rendering.
    Reads from in-memory event log; columns: id, roas, prediction, error,
    cost, revenue, env_regime, env_trend, pred_width, interval_conf.
    """
    rows = _core._state.event_log.rows[-limit:]
    keep = {
        "roas", "prediction", "error", "cost", "revenue",
        "env_regime", "env_trend", "pred_width", "interval_conf",
        "roas_6h", "roas_12h", "roas_24h", "variant",
    }
    result = []
    for i, r in enumerate(rows):
        row = {k: v for k, v in r.items() if k in keep}
        row["idx"] = i
        result.append(row)
    return result


@router.get("/causal")
def causal():
    """Causal graph edges sorted by Granger weight."""
    return [
        {"from": p, "to": c, "weight": round(w, 4)}
        for (p, c), w in sorted(
            _core._state.graph.edges.items(), key=lambda x: abs(x[1]), reverse=True
        )
    ]


@router.get("/drift")
def drift():
    """Latest Evidently drift report JSON, if available."""
    import json
    import os
    for candidate in ["drift_report.json", "state/drift_report.json"]:
        if os.path.exists(candidate):
            try:
                with open(candidate) as f:
                    return json.load(f)
            except Exception:
                break
    return {"available": False}


@router.get("/memory")
def memory():
    """Last 20 learning memory rows."""
    recent = _core._state.memory[-20:]
    return [
        {k: round(v, 4) if isinstance(v, float) else v for k, v in r.items()}
        for r in recent
    ]


@router.get("/agent-metrics")
def agent_metrics():
    """Per-agent PnL, decision counts, and drift status."""
    try:
        from backend.agents.agent_metrics import agent_metrics_registry
        return {"agents": agent_metrics_registry.snapshot()}
    except Exception:
        return {"agents": []}


__all__ = ["router"]
