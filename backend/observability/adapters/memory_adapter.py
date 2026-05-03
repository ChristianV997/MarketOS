"""memory_adapter — emit hierarchical memory events into observability."""
from __future__ import annotations

import time
from typing import Any


def emit_memory_gauges() -> None:
    try:
        from ..telemetry_router import get_telemetry_router
        get_telemetry_router().update_memory_gauges()
    except Exception:
        pass


def emit_episodic_recorded(episode_id: str, event_type: str) -> None:
    try:
        from ..metrics import episodic_count
        from backend.memory.episodic import get_episodic_store
        episodic_count.set(get_episodic_store().count())
    except Exception:
        pass


def emit_semantic_updated(domain: str, generation: int) -> None:
    try:
        from ..metrics import semantic_count, semantic_generation
        from backend.memory.semantic import get_semantic_store
        store = get_semantic_store()
        semantic_count.labels(domain=domain).set(store.count(domain))
        semantic_generation.set(generation)
    except Exception:
        pass


def emit_procedural_updated() -> None:
    try:
        from ..metrics import procedural_count
        from backend.memory.procedural import get_procedural_store
        procedural_count.set(get_procedural_store().count())
    except Exception:
        pass


def memory_summary(workspace: str = "default") -> dict[str, Any]:
    """Return counts from all memory tiers."""
    result: dict[str, Any] = {"workspace": workspace, "ts": time.time()}
    try:
        from backend.memory.episodic import get_episodic_store
        result["episodic_count"] = get_episodic_store().count()
    except Exception:
        result["episodic_count"] = 0
    try:
        from backend.memory.semantic import get_semantic_store
        store = get_semantic_store()
        result["semantic_total"] = store.count()
        result["semantic_generation"] = store.generation()
    except Exception:
        result["semantic_total"] = 0
        result["semantic_generation"] = 0
    try:
        from backend.memory.procedural import get_procedural_store
        result["procedural_count"] = get_procedural_store().count()
    except Exception:
        result["procedural_count"] = 0
    return result
