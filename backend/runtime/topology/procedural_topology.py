"""procedural_topology — build topology nodes from ProceduralStore."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .schemas.node import TopologyNode

if TYPE_CHECKING:
    from .topology_graph import TopologyGraph


def populate_procedural(graph: "TopologyGraph", workspace: str = "default") -> int:
    added = 0
    try:
        from backend.memory.procedural import get_procedural_store
        store = get_procedural_store()
        for proc in store.snapshot():
            node = TopologyNode(
                node_id=f"proc:{proc.get('procedure_id', proc.get('key', ''))}",
                node_type="procedural",
                workspace=workspace,
                label=proc.get("key", ""),
                score=proc.get("success_rate", 0.0),
                metadata={
                    "domain": proc.get("domain", ""),
                    "avg_roas": proc.get("avg_roas", 0.0),
                },
            )
            graph.add_node(node)
            added += 1
    except Exception:
        pass
    return added
