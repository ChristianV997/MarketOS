"""exporters — export observability data to Prometheus / JSON."""
from __future__ import annotations

import json
import time
from typing import Any


def prometheus_text() -> str:
    """Return current Prometheus metrics as text/plain."""
    try:
        from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
        return generate_latest().decode("utf-8")
    except Exception:
        return "# prometheus_client not available\n"


def cognition_json(workspace: str = "default") -> dict[str, Any]:
    """Full cognition state as JSON-serializable dict."""
    from .schemas.cognition_snapshot import CognitionSnapshot
    return CognitionSnapshot.capture(workspace=workspace).to_dict()


def entropy_json(workspace: str = "default") -> dict[str, Any]:
    """Current entropy report as JSON-serializable dict."""
    from .entropy_metrics import measure_entropy
    return measure_entropy(workspace=workspace).to_dict()


def recent_traces_json(n: int = 20) -> list[dict[str, Any]]:
    """Last n completed traces as JSON-serializable list."""
    from .tracing import tracer
    return [t.to_dict() for t in tracer.recent_traces(n)]


def topology_json(workspace: str = "default") -> dict[str, Any]:
    """Current topology snapshot as JSON-serializable dict."""
    try:
        from backend.runtime.topology.topology_snapshot import capture_topology_snapshot
        return capture_topology_snapshot(workspace=workspace).to_dict()
    except Exception:
        return {"error": "topology not available", "workspace": workspace, "ts": time.time()}
