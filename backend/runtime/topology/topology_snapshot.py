"""topology_snapshot — capture a serializable topology snapshot."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .workspace_topology import build_workspace_topology
from .entropy_map import entropy_overlay


@dataclass
class TopologySnapshot:
    snapshot_id: str
    workspace: str
    ts: float
    node_types: dict[str, int]
    total_nodes: int
    total_edges: int
    depth_histogram: dict[str, int]
    entropy: dict[str, Any]
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "workspace": self.workspace,
            "ts": self.ts,
            "node_types": self.node_types,
            "total_nodes": self.total_nodes,
            "total_edges": self.total_edges,
            "depth_histogram": self.depth_histogram,
            "entropy": self.entropy,
            "nodes": self.nodes,
            "edges": self.edges,
        }


def capture_topology_snapshot(workspace: str = "default") -> TopologySnapshot:
    """Build and return a full topology snapshot."""
    graph = build_workspace_topology(workspace)
    entropy = entropy_overlay(workspace)
    return TopologySnapshot(
        snapshot_id=uuid.uuid4().hex[:16],
        workspace=workspace,
        ts=time.time(),
        node_types=graph.node_types(),
        total_nodes=len(graph.nodes()),
        total_edges=len(graph.edges()),
        depth_histogram=graph.depth_histogram(),
        entropy=entropy,
        nodes=[n.to_dict() for n in graph.nodes()],
        edges=[e.to_dict() for e in graph.edges()],
    )
