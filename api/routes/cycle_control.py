"""api.routes.cycle_control — manual cycle trigger + background runner pause/resume."""
from __future__ import annotations

import threading
import time

from fastapi import APIRouter, Depends

from backend import api as _core
from backend.identity.operator_gates import runtime_control_gate
from backend.identity.workspaces import WorkspaceAccess

router = APIRouter()


@router.post("/cycle")
def cycle(_access: WorkspaceAccess = Depends(runtime_control_gate)):
    """Trigger one manual cycle (useful for testing / Replit buttons)."""
    from backend.execution.loop import run_cycle

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
def pause_runner(_access: WorkspaceAccess = Depends(runtime_control_gate)):
    """Pause the background cycle runner."""
    _core._bg_running = False
    return {"bg_running": False}


@router.post("/runner/resume")
def resume_runner(_access: WorkspaceAccess = Depends(runtime_control_gate)):
    """Resume the background cycle runner if paused."""
    if not _core._bg_running:
        _core._bg_running = True
        threading.Thread(target=_core._background_runner, daemon=True).start()
    return {"bg_running": True}


__all__ = ["router"]
