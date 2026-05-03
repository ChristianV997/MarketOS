"""scheduler_adapter — emit sleep scheduler events into observability."""
from __future__ import annotations

import time
from typing import Any


def emit_sleep_cycle(duration_ms: float, compression_ratio: float, units_created: int) -> None:
    try:
        from ..telemetry_router import get_telemetry_router
        get_telemetry_router().record_sleep_cycle(duration_ms, compression_ratio, units_created)
    except Exception:
        pass


def emit_cycle_result(result: Any) -> None:
    """Emit metrics from a ConsolidationResult object."""
    try:
        duration_ms = getattr(result, "duration_ms", 0.0) or 0.0
        compression = getattr(result, "compression_ratio", 1.0) or 1.0
        units = getattr(result, "semantic_units_created", 0) or 0
        emit_sleep_cycle(duration_ms, compression, units)
    except Exception:
        pass


def scheduler_status() -> dict[str, Any]:
    """Return current scheduler state."""
    try:
        from backend.runtime.sleep.replay_scheduler import get_scheduler
        s = get_scheduler()
        return {
            "running": s.is_running(),
            "cycles_completed": s.cycles_completed,
            "last_cycle_at": s.last_cycle_at,
            "interval_s": s.interval_s,
            "ts": time.time(),
        }
    except Exception:
        return {"running": False, "cycles_completed": 0, "last_cycle_at": None, "ts": time.time()}
