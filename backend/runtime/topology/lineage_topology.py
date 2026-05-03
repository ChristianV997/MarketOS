"""lineage_topology — build topology nodes/edges from LineageGraph."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .schemas.node import TopologyNode
from .schemas.edge import TopologyEdge

if TYPE_CHECKING:
    from .topology_graph import TopologyGraph


def populate_lineage(graph: "TopologyGraph", workspace: str = "default", limit: int = 200) -> int:
    added = 0
    try:
        from backend.lineage import get_tracker
        tracker = get_tracker()
        lg = tracker.graph()
        nodes = lg.nodes_by_workspace(workspace)[:limit]
        for n in nodes:
            topo_node = TopologyNode(
                node_id=f"lin:{n.node_id}",
                node_type="lineage",
                workspace=workspace,
                label=n.event_type,
                ts=n.ts,
                metadata={"source": n.source, "parent_ids": n.parent_ids},
            )
            graph.add_node(topo_node)
            added += 1
        for n in nodes:
            for pid in n.parent_ids:
                graph.add_edge(TopologyEdge(
                    source_id=f"lin:{pid}",
                    target_id=f"lin:{n.node_id}",
                    edge_type="lineage",
                ))
    except Exception:
        pass
    return added
