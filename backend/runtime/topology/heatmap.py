"""heatmap — compute activity heatmap over topology nodes."""
from __future__ import annotations

import time
from typing import Any

from .topology_graph import TopologyGraph


def activity_heatmap(graph: TopologyGraph, window_s: float = 3600.0) -> dict[str, Any]:
    """Return node activity counts per node_type within the time window."""
    now = time.time()
    cutoff = now - window_s
    counts: dict[str, int] = {}
    hottest: list[dict[str, Any]] = []

    for node in graph.nodes():
        if node.ts >= cutoff:
            counts[node.node_type] = counts.get(node.node_type, 0) + 1
            hottest.append({"node_id": node.node_id, "label": node.label,
                            "node_type": node.node_type, "score": node.score, "ts": node.ts})

    hottest.sort(key=lambda x: x["score"], reverse=True)

    return {
        "window_s": window_s,
        "counts_by_type": counts,
        "top_nodes": hottest[:20],
        "total_active": sum(counts.values()),
        "ts": now,
    }
