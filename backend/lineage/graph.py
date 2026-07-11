"""LineageGraph — directed acyclic graph of causal dependencies.

The graph is built from LineageNodes where edges point from child → parents.
All traversal operations are backward-only (ancestry) or forward
(descendants), allowing full replay trajectory reconstruction.
"""
from __future__ import annotations

import os
import threading
from collections import OrderedDict
from typing import Iterator

from .node import LineageNode

# Cap the graph so a long-running process cannot accumulate nodes without
# bound. Oldest nodes are evicted FIFO; stale child references to evicted
# nodes are harmless (traversal skips missing node_ids).
_MAX_NODES = int(os.getenv("LINEAGE_MAX_NODES", "50000"))


class LineageGraph:
    """Thread-safe DAG of LineageNodes.

    Nodes are stored by node_id.  Parent→child adjacency is maintained
    in a separate index for forward traversal.
    """

    def __init__(self, max_nodes: int = _MAX_NODES) -> None:
        self._lock:       threading.Lock                     = threading.Lock()
        self._nodes:      "OrderedDict[str, LineageNode]"    = OrderedDict()
        self._children:   dict[str, list[str]]               = {}  # parent_id → [child_ids]
        self._max_nodes = max_nodes

    # ── writes ────────────────────────────────────────────────────────────────

    def add_node(self, node: LineageNode) -> None:
        with self._lock:
            self._nodes[node.node_id] = node
            self._nodes.move_to_end(node.node_id)
            for pid in node.parent_ids:
                self._children.setdefault(pid, []).append(node.node_id)
            while len(self._nodes) > self._max_nodes:
                evicted_id, _ = self._nodes.popitem(last=False)
                self._children.pop(evicted_id, None)

    # ── reads ─────────────────────────────────────────────────────────────────

    def get(self, node_id: str) -> LineageNode | None:
        with self._lock:
            return self._nodes.get(node_id)

    def ancestors(self, node_id: str, depth: int = 50) -> list[LineageNode]:
        """BFS backward through parent_ids up to *depth* hops."""
        visited: set[str] = set()
        queue   = [node_id]
        result  = []
        hops    = 0
        with self._lock:
            while queue and hops < depth:
                next_q: list[str] = []
                for nid in queue:
                    if nid in visited:
                        continue
                    visited.add(nid)
                    node = self._nodes.get(nid)
                    if node and nid != node_id:
                        result.append(node)
                    if node:
                        next_q.extend(node.parent_ids)
                queue = next_q
                hops += 1
        return result

    def descendants(self, node_id: str, depth: int = 50) -> list[LineageNode]:
        """BFS forward through children index up to *depth* hops."""
        visited: set[str] = set()
        queue   = [node_id]
        result  = []
        hops    = 0
        with self._lock:
            while queue and hops < depth:
                next_q: list[str] = []
                for nid in queue:
                    if nid in visited:
                        continue
                    visited.add(nid)
                    node = self._nodes.get(nid)
                    if node and nid != node_id:
                        result.append(node)
                    next_q.extend(self._children.get(nid, []))
                queue = next_q
                hops += 1
        return result

    def lineage_chain(self, node_id: str) -> list[str]:
        """Return [root_id, ..., node_id] — ordered ancestry chain."""
        ancestors = self.ancestors(node_id)
        chain = [n.node_id for n in sorted(ancestors, key=lambda n: n.ts)]
        chain.append(node_id)
        return chain

    def nodes_by_type(self, node_type: str) -> list[LineageNode]:
        with self._lock:
            return [n for n in self._nodes.values() if n.node_type == node_type]

    def nodes_by_workspace(self, workspace: str) -> list[LineageNode]:
        with self._lock:
            return [n for n in self._nodes.values() if n.workspace == workspace]

    def count(self) -> int:
        with self._lock:
            return len(self._nodes)

    def all_nodes(self) -> list[LineageNode]:
        with self._lock:
            return list(self._nodes.values())

    # ── persistence ─────────────────────────────────────────────────────────

    def snapshot(self) -> list[dict]:
        """Return a JSON-safe list of all nodes (insertion order)."""
        with self._lock:
            return [n.to_dict() for n in self._nodes.values()]

    def restore(self, nodes: list[dict]) -> None:
        """Rebuild the graph from a snapshot produced by ``snapshot()``."""
        with self._lock:
            self._nodes.clear()
            self._children.clear()
            for d in nodes or []:
                try:
                    node = LineageNode.from_dict(d)
                except Exception:
                    continue
                self._nodes[node.node_id] = node
                for pid in node.parent_ids:
                    self._children.setdefault(pid, []).append(node.node_id)
            while len(self._nodes) > self._max_nodes:
                evicted_id, _ = self._nodes.popitem(last=False)
                self._children.pop(evicted_id, None)
