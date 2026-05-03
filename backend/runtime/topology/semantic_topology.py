"""semantic_topology — build topology nodes from the SemanticStore."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .schemas.node import TopologyNode
from .schemas.edge import TopologyEdge

if TYPE_CHECKING:
    from .topology_graph import TopologyGraph


def populate_semantic(graph: "TopologyGraph", workspace: str = "default") -> int:
    """Add SemanticStore units as topology nodes. Returns count added."""
    added = 0
    try:
        from backend.memory.semantic import get_semantic_store
        store = get_semantic_store()
        for domain in ["hook", "angle", "signal", "product"]:
            for unit in store.top_by_score(domain, k=100):
                node = TopologyNode(
                    node_id=f"sem:{unit.unit_id}",
                    node_type="semantic",
                    workspace=workspace,
                    label=unit.label,
                    score=unit.score,
                    metadata={"domain": domain, "generation": unit.generation},
                )
                graph.add_node(node)
                added += 1
    except Exception:
        pass
    return added
