"""topology_graph — in-memory directed graph of cognitive topology nodes."""
from __future__ import annotations

import threading
from typing import Any

from .schemas.node import TopologyNode
from .schemas.edge import TopologyEdge


class TopologyGraph:
    """Thread-safe directed graph over TopologyNode objects."""

    def __init__(self) -> None:
        self._nodes: dict[str, TopologyNode] = {}
        self._edges: list[TopologyEdge] = []
        self._lock = threading.Lock()

    def add_node(self, node: TopologyNode) -> None:
        with self._lock:
            self._nodes[node.node_id] = node

    def add_edge(self, edge: TopologyEdge) -> None:
        with self._lock:
            self._edges.append(edge)

    def node(self, node_id: str) -> TopologyNode | None:
        with self._lock:
            return self._nodes.get(node_id)

    def nodes(self, node_type: str | None = None, workspace: str | None = None) -> list[TopologyNode]:
        with self._lock:
            result = list(self._nodes.values())
        if node_type:
            result = [n for n in result if n.node_type == node_type]
        if workspace:
            result = [n for n in result if n.workspace == workspace]
        return result

    def edges(self, source_id: str | None = None) -> list[TopologyEdge]:
        with self._lock:
            result = list(self._edges)
        if source_id:
            result = [e for e in result if e.source_id == source_id]
        return result

    def node_types(self) -> dict[str, int]:
        """Return count per node_type."""
        counts: dict[str, int] = {}
        for node in self.nodes():
            counts[node.node_type] = counts.get(node.node_type, 0) + 1
        return counts

    def depth_histogram(self) -> dict[str, int]:
        """BFS depth distribution from root nodes (no incoming edges)."""
        with self._lock:
            targets = {e.target_id for e in self._edges}
            roots = [nid for nid in self._nodes if nid not in targets]

        hist: dict[str, int] = {}
        visited: set[str] = set()
        queue = [(nid, 0) for nid in roots]
        while queue:
            nid, depth = queue.pop(0)
            if nid in visited:
                continue
            visited.add(nid)
            key = str(depth)
            hist[key] = hist.get(key, 0) + 1
            for e in self.edges(source_id=nid):
                if e.target_id not in visited:
                    queue.append((e.target_id, depth + 1))
        return hist

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in self.nodes()],
            "edges": [e.to_dict() for e in self.edges()],
        }

    def clear(self) -> None:
        with self._lock:
            self._nodes.clear()
            self._edges.clear()
