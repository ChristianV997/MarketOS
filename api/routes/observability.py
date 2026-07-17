"""api.routes.observability — Prometheus, phase, topology, and misc system introspection."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from backend import api as _core

router = APIRouter()


@router.get("/metrics/prometheus", response_class=PlainTextResponse)
def prometheus_metrics():
    """Prometheus scrape endpoint — exposes all registered metrics."""
    if not _core._PROMETHEUS_OK:
        return PlainTextResponse("# prometheus_client not installed\n", media_type="text/plain")
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/phase")
def phase_status():
    """Current lifecycle phase and promotion KPIs."""
    try:
        from core.system.phase_controller import phase_controller
        from core.system.resource_allocator import resource_allocator
        status = phase_controller.status()
        alloc  = resource_allocator.describe(
            phase_controller.current,
            total_budget=500.0,
        )
        return {"phase": status, "allocation": alloc}
    except Exception:
        return {"phase": {"phase": "RESEARCH"}, "allocation": {}}


@router.get("/macro")
def macro():
    """Latest FRED macro signals (falls back to static stubs when key absent)."""
    from connectors.macro_signals import get_macro_signals
    try:
        return get_macro_signals()
    except Exception:
        return {"error": "macro signals unavailable"}


@router.get("/replay_buffer")
def replay_buffer_stats():
    """Replay buffer size and readiness."""
    from backend.learning.replay_buffer import replay_buffer as _rb
    return {
        "size": len(_rb),
        "capacity": _rb.capacity,
        "ready": _rb.is_ready(),
    }


@router.get("/bandit")
def bandit_status():
    """LinUCB contextual bandit arm registry (arm names only)."""
    from backend.learning.contextual_bandit import bandit_instance
    b = bandit_instance()
    return {"arms": b.arms, "alpha": b.alpha}


@router.get("/snapshot")
def snapshot():
    """Full runtime snapshot — used by dashboard on initial load before WS connects."""
    try:
        from backend.runtime.state import build_snapshot
        with _core._lock:
            snap = build_snapshot(_core._state)
        return snap.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


@router.get("/runtime/tasks")
def runtime_tasks():
    """Live task inventory: all loops, schedulers, Celery tasks, queues, WS emitters,
    and state writers with their current status and heartbeat timestamps."""
    try:
        from backend.runtime.task_inventory import task_registry
        return {
            "summary": task_registry.summary(),
            "live_threads": task_registry.live_threads(),
            "tasks": task_registry.all(),
        }
    except Exception as exc:
        return {"error": str(exc)}


@router.get("/playbook")
def get_playbook(product: str = None):
    """Return stored playbooks and content patterns. Filter by ?product= if desired."""
    try:
        from core.content.playbook import playbook_memory
        from core.content.patterns import pattern_store
        playbooks = playbook_memory.all()
        if product:
            pb = playbook_memory.get(product)
            playbooks = [pb] if pb else []
        return {
            "playbooks": [vars(p) for p in playbooks],
            "patterns":  pattern_store.get_patterns(),
        }
    except Exception as exc:
        return {"error": str(exc)}


@router.get("/runtime/state")
def runtime_state():
    """Return full canonical RuntimeState as JSON."""
    try:
        from backend.runtime.state import build_runtime_state
        rs = build_runtime_state(_core._state)
        return rs.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


@router.get("/observability/snapshot")
def observability_snapshot(workspace: str = "default"):
    """Full CognitionSnapshot for the given workspace."""
    try:
        from backend.observability.exporters import cognition_json
        return cognition_json(workspace=workspace)
    except Exception as exc:
        return {"error": str(exc), "workspace": workspace}


@router.get("/observability/entropy")
def observability_entropy(workspace: str = "default"):
    """Current entropy report for the workspace."""
    try:
        from backend.observability.exporters import entropy_json
        return entropy_json(workspace=workspace)
    except Exception as exc:
        return {"error": str(exc), "workspace": workspace}


@router.get("/observability/traces")
def observability_traces(n: int = 20):
    """Last n completed traces."""
    try:
        from backend.observability.exporters import recent_traces_json
        return recent_traces_json(n=n)
    except Exception as exc:
        return {"error": str(exc)}


@router.get("/topology")
def topology(workspace: str = "default"):
    """Full topology snapshot for the workspace."""
    try:
        from backend.runtime.topology.topology_snapshot import capture_topology_snapshot
        return capture_topology_snapshot(workspace=workspace).to_dict()
    except Exception as exc:
        return {"error": str(exc), "workspace": workspace}


@router.get("/topology/cognition")
def topology_cognition(workspace: str = "default"):
    """High-level cognitive state map: topology + entropy + heatmap."""
    try:
        from backend.runtime.topology.cognition_map import cognition_map
        return cognition_map(workspace=workspace)
    except Exception as exc:
        return {"error": str(exc), "workspace": workspace}


@router.get("/topology/entropy")
def topology_entropy(workspace: str = "default"):
    """Per-node-type entropy overlay for the workspace."""
    try:
        from backend.runtime.topology.entropy_map import entropy_overlay
        return entropy_overlay(workspace=workspace)
    except Exception as exc:
        return {"error": str(exc), "workspace": workspace}


@router.get("/governance/schemas")
def governance_schemas():
    """Return all registered schema versions."""
    try:
        from backend.contracts.governance.registry import get_governance_registry
        return get_governance_registry().to_dict()
    except Exception as exc:
        return {"error": str(exc)}


__all__ = ["router"]
