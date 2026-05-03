"""Tests for graph_compaction."""
import time
from backend.runtime.topology.topology_graph import TopologyGraph
from backend.runtime.topology.schemas.node import TopologyNode
from backend.runtime.topology.schemas.edge import TopologyEdge
from backend.runtime.topology.graph_compaction import compact_graph


def _old_node(node_id: str) -> TopologyNode:
    n = TopologyNode(node_id=node_id, node_type="semantic", workspace="test", label=node_id)
    n.ts = time.time() - 100000  # very old
    return n


def test_compact_removes_old_nodes():
    g = TopologyGraph()
    g.add_node(_old_node("old1"))
    g.add_node(_old_node("old2"))
    fresh = TopologyNode("fresh", "semantic", workspace="test", label="fresh")
    g.add_node(fresh)
    removed = compact_graph(g, max_age_s=3600.0)
    assert removed == 2
    assert g.node("old1") is None
    assert g.node("fresh") is not None


def test_compact_removes_dangling_edges():
    g = TopologyGraph()
    old = _old_node("old")
    fresh = TopologyNode("fresh", "semantic", workspace="test", label="fresh")
    g.add_node(old)
    g.add_node(fresh)
    g.add_edge(TopologyEdge("old", "fresh"))
    compact_graph(g, max_age_s=3600.0)
    assert g.edges() == []


def test_compact_cap():
    g = TopologyGraph()
    for i in range(10):
        n = TopologyNode(f"n{i}", "semantic", workspace="test", label=f"n{i}")
        n.ts = time.time() - i * 10
        g.add_node(n)
    compact_graph(g, max_age_s=99999.0, max_nodes=5)
    assert len(g.nodes()) == 5
