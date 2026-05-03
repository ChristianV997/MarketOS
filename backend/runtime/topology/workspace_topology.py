"""workspace_topology — aggregate all sub-topologies for a workspace."""
from __future__ import annotations

from .topology_graph import TopologyGraph
from .semantic_topology import populate_semantic
from .procedural_topology import populate_procedural
from .lineage_topology import populate_lineage
from .replay_topology import populate_replay


def build_workspace_topology(workspace: str = "default") -> TopologyGraph:
    """Construct a full topology graph for a workspace."""
    graph = TopologyGraph()
    populate_semantic(graph, workspace)
    populate_procedural(graph, workspace)
    populate_lineage(graph, workspace)
    populate_replay(graph, workspace)
    return graph
