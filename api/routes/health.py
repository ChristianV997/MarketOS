"""api.routes.health — uptime and lightweight status polling."""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend import api as _core
from backend.runtime.deployment_status import mvp_deployment_status

router = APIRouter()


def _mvp_deployment_status() -> dict[str, object]:
    """Expose safe deployment booleans without returning configuration values."""
    return mvp_deployment_status()


@router.get("/health")
def health():
    """Replit uptime monitor / health check."""
    return {"ok": True, "mvp": _mvp_deployment_status()}


@router.get("/ready")
def ready():
    """Readiness probe that waits for the application lifespan to initialize."""
    from backend.security.deployment_validation import validate_production_deployment
    deploy_check = validate_production_deployment()
    if deploy_check.get("production_mode") and not deploy_check.get("ready"):
        return JSONResponse(
            {
                "ready": False,
                "reason": "production_security_preflight_failed",
                "blockers": deploy_check.get("blockers"),
                "mvp": _mvp_deployment_status(),
            },
            status_code=503,
        )
    if not _core._bg_running or not _core._runtime_services_ready:
        return JSONResponse(
            {"ready": False, "reason": "runtime_services_initializing", "mvp": _mvp_deployment_status()},
            status_code=503,
        )
    if os.getenv("MEDUSA_REQUIRED_FOR_READY", "false").lower() == "true":
        from backend.integrations.medusa import commerce_provider
        medusa_health = commerce_provider.health()
        if not medusa_health.reachable:
            return JSONResponse(
                {"ready": False, "reason": "required_medusa_unavailable", "detail": medusa_health.detail, "mvp": _mvp_deployment_status()},
                status_code=503,
            )
    return {"ready": True, "mvp": _mvp_deployment_status(), "security": deploy_check}


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
