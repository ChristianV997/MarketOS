"""cognition_map — high-level cognitive state map combining topology + entropy."""
from __future__ import annotations

import time
from typing import Any

from .workspace_topology import build_workspace_topology
from .entropy_map import entropy_overlay
from .heatmap import activity_heatmap


def cognition_map(workspace: str = "default") -> dict[str, Any]:
    """Return a full cognitive state map for a workspace."""
    graph = build_workspace_topology(workspace)
    entropy = entropy_overlay(workspace)
    heatmap = activity_heatmap(graph)

    return {
        "workspace": workspace,
        "ts": time.time(),
        "node_types": graph.node_types(),
        "total_nodes": len(graph.nodes()),
        "total_edges": len(graph.edges()),
        "depth_histogram": graph.depth_histogram(),
        "entropy": entropy,
        "heatmap": heatmap,
    }
