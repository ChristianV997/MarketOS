"""api.routes.health — uptime and lightweight status polling."""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend import api as _core

router = APIRouter()


@router.get("/health")
def health():
    """Replit uptime monitor / health check."""
    return {"ok": True}


@router.get("/ready")
def ready():
    """Readiness probe that waits for the application lifespan to initialize."""
    if not _core._bg_running or not _core._runtime_services_ready:
        return JSONResponse(
            {"ready": False, "reason": "runtime_services_initializing"},
            status_code=503,
        )
    if os.getenv("MEDUSA_REQUIRED_FOR_READY", "false").lower() == "true":
        from backend.integrations.medusa import commerce_provider
        medusa_health = commerce_provider.health()
        if not medusa_health.reachable:
            return JSONResponse(
                {"ready": False, "reason": "required_medusa_unavailable", "detail": medusa_health.detail},
                status_code=503,
            )
    return {"ready": True}


@router.get("/status")
def status():
    """Lightweight status snapshot for polling."""
    uptime = round(time.time() - _core._started_at, 1)
    last = (
        datetime.fromtimestamp(_core._last_cycle_at, tz=timezone.utc).isoformat()
        if _core._last_cycle_at else None
    )
    state = _core._state
    return {
        "capital": round(state.capital, 2),
        "regime": state.regime,
        "detected_regime": state.detected_regime,
        "energy": state.energy,
        "event_count": len(state.event_log.rows),
        "memory_size": len(state.memory),
        "causal_edges": len(state.graph.edges),
        "total_cycles": state.total_cycles,
        "uptime_s": uptime,
        "last_cycle_at": last,
        "bg_running": _core._bg_running,
    }


__all__ = ["router"]
