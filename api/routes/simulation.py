"""api.routes.simulation — simulation layer scores, health report, and calibration audit."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/simulation/scores")
def simulation_scores(limit: int = 20):
    """Return top-ranked simulation scores from the most recent scoring run."""
    try:
        from simulation.engine import simulation_engine
        from core.signals import signal_engine as _sig
        from core.content.patterns import pattern_store
        from core.content.playbook import playbook_memory

        patterns = pattern_store.get_patterns()
        all_playbooks = {p.product: p for p in playbook_memory.all()}
        signals = _sig.get()[:limit]
        ranked = simulation_engine.score_signals(
            signals,
            patterns=patterns,
            playbooks=all_playbooks,
        )
        return {
            "scores": [r.to_dict() for r in ranked],
            "total": len(ranked),
            "model_info": simulation_engine.report().get("model", {}),
        }
    except Exception as exc:
        return {"error": str(exc), "scores": []}


@router.get("/simulation/report")
def simulation_report():
    """Return simulation layer health: calibration stats, model info, replay row count."""
    try:
        from simulation.engine import simulation_engine
        return simulation_engine.report()
    except Exception as exc:
        return {"error": str(exc)}


@router.get("/simulation/calibration")
def simulation_calibration():
    """Return prediction-vs-reality calibration audit (MAE, RMSE, bias, per-product)."""
    try:
        from simulation.calibration import calibration_store
        return calibration_store.summary()
    except Exception as exc:
        return {"error": str(exc)}


__all__ = ["router"]
