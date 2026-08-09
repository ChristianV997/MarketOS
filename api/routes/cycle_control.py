"""api.routes.cycle_control — manual cycle trigger + background runner pause/resume."""
from __future__ import annotations

import threading
import time

from fastapi import APIRouter

from backend import api as _core
from backend.execution.loop import run_cycle

router = APIRouter()


@router.post("/cycle")
def cycle():
    """Trigger one manual cycle (useful for testing / Replit buttons)."""
    new_state = run_cycle(_core._state)
    with _core._lock:
        _core._state = new_state
        _core._last_cycle_at = time.time()
    return {
        "capital": round(_core._state.capital, 2),
        "total_cycles": _core._state.total_cycles,
        "event_count": len(_core._state.event_log.rows),
        "detected_regime": _core._state.detected_regime,
    }


@router.post("/runner/pause")
def pause_runner():
    """Pause the background cycle runner."""
    _core._bg_running = False
    return {"bg_running": False}


@router.post("/runner/resume")
def resume_runner():
    """Resume the background cycle runner if paused."""
    if not _core._bg_running:
        _core._bg_running = True
        threading.Thread(target=_core._background_runner, daemon=True).start()
    return {"bg_running": True}


__all__ = ["router"]
