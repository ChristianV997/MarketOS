"""lineage_adapter — emit lineage events into the observability layer."""
from __future__ import annotations

import time
from typing import Any


def emit_lineage_tracked(
    node_id: str,
    workspace: str,
    source: str,
    parent_ids: list[str],
    event_type: str = "",
) -> None:
    """Record a new lineage node in telemetry."""
    try:
        from ..metrics import lineage_nodes_total
        lineage_nodes_total.inc()
    except Exception:
        pass
    try:
        from ..telemetry_router import get_telemetry_router
        get_telemetry_router().update_lineage_gauges()
    except Exception:
        pass
    try:
        from backend.events.log import append
        append(
            "observability.lineage.tracked",
            payload={
                "node_id": node_id,
                "workspace": workspace,
                "source": source,
                "parent_ids": parent_ids,
                "event_type": event_type,
                "ts": time.time(),
            },
            source="lineage_adapter",
        )
    except Exception:
        pass


def emit_worldline_step(
    worldline_id: str,
    node_id: str,
    workspace: str,
) -> None:
    """Record a worldline step extension."""
    try:
        from ..metrics import lineage_worldlines_total
        lineage_worldlines_total.inc()
    except Exception:
        pass
    try:
        from backend.events.log import append
        append(
            "observability.worldline.step",
            payload={
                "worldline_id": worldline_id,
                "node_id": node_id,
                "workspace": workspace,
                "ts": time.time(),
            },
            source="lineage_adapter",
        )
    except Exception:
        pass


def lineage_summary(workspace: str = "default") -> dict[str, Any]:
    """Return a lineage count summary for the given workspace."""
    try:
        from backend.lineage import get_tracker
        t = get_tracker()
        return {
            "workspace": workspace,
            "node_count": t.node_count(),
            "worldline_count": t.worldline_count(),
            "ts": time.time(),
        }
    except Exception:
        return {"workspace": workspace, "node_count": 0, "worldline_count": 0, "ts": time.time()}
