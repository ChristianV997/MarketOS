"""graph_compaction — prune stale topology nodes to bound memory."""
from __future__ import annotations

import time

from .topology_graph import TopologyGraph


def compact_graph(graph: TopologyGraph, max_age_s: float = 86400.0, max_nodes: int = 5000) -> int:
    """Remove nodes older than max_age_s or exceed max_nodes cap. Returns removed count."""
    now = time.time()
    cutoff = now - max_age_s

    with graph._lock:
        # Age-based pruning
        stale = [nid for nid, n in graph._nodes.items() if n.ts < cutoff]
        for nid in stale:
            del graph._nodes[nid]

        # Cap-based pruning (remove oldest first)
        if len(graph._nodes) > max_nodes:
            sorted_nodes = sorted(graph._nodes.items(), key=lambda kv: kv[1].ts)
            excess = len(graph._nodes) - max_nodes
            for nid, _ in sorted_nodes[:excess]:
                del graph._nodes[nid]
                stale.append(nid)

        # Remove dangling edges
        stale_set = set(stale)
        graph._edges = [
            e for e in graph._edges
            if e.source_id not in stale_set and e.target_id not in stale_set
        ]

    return len(stale)
