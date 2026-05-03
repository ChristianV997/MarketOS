"""replay_topology — build topology nodes from the replay store."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from .schemas.node import TopologyNode
from .schemas.edge import TopologyEdge

if TYPE_CHECKING:
    from .topology_graph import TopologyGraph


def populate_replay(graph: "TopologyGraph", workspace: str = "default", limit: int = 100) -> int:
    added = 0
    try:
        from backend.runtime.replay_store import get_replay_store
        store = get_replay_store()
        rows = store.recent(limit)
        prev_id: str | None = None
        for row in rows:
            node_id = f"replay:{row.get('event_id', row.get('id', ''))}"
            node = TopologyNode(
                node_id=node_id,
                node_type="replay",
                workspace=workspace,
                label=row.get("event_type", ""),
                ts=row.get("ts", time.time()),
                metadata={"source": row.get("source", "")},
            )
            graph.add_node(node)
            added += 1
            if prev_id:
                graph.add_edge(TopologyEdge(
                    source_id=prev_id,
                    target_id=node_id,
                    edge_type="replay",
                ))
            prev_id = node_id
    except Exception:
        pass
    return added
