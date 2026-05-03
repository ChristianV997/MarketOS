"""Tests for topology_graph."""
import time
from backend.runtime.topology.topology_graph import TopologyGraph
from backend.runtime.topology.schemas.node import TopologyNode
from backend.runtime.topology.schemas.edge import TopologyEdge


def _node(node_id: str, node_type: str = "semantic") -> TopologyNode:
    return TopologyNode(node_id=node_id, node_type=node_type, workspace="test", label=node_id)


def test_add_node_and_retrieve():
    g = TopologyGraph()
    g.add_node(_node("n1"))
    assert g.node("n1") is not None


def test_node_filter_by_type():
    g = TopologyGraph()
    g.add_node(_node("n1", "semantic"))
    g.add_node(_node("n2", "lineage"))
    assert len(g.nodes(node_type="semantic")) == 1


def test_node_filter_by_workspace():
    g = TopologyGraph()
    g.add_node(TopologyNode("n1", "semantic", workspace="ws1", label="n1"))
    g.add_node(TopologyNode("n2", "semantic", workspace="ws2", label="n2"))
    assert len(g.nodes(workspace="ws1")) == 1


def test_add_edge_and_retrieve():
    g = TopologyGraph()
    g.add_node(_node("a"))
    g.add_node(_node("b"))
    g.add_edge(TopologyEdge("a", "b"))
    edges = g.edges(source_id="a")
    assert len(edges) == 1
    assert edges[0].target_id == "b"


def test_node_types_count():
    g = TopologyGraph()
    g.add_node(_node("n1", "semantic"))
    g.add_node(_node("n2", "semantic"))
    g.add_node(_node("n3", "lineage"))
    types = g.node_types()
    assert types["semantic"] == 2
    assert types["lineage"] == 1


def test_depth_histogram_single_chain():
    g = TopologyGraph()
    for i in range(3):
        g.add_node(_node(f"n{i}"))
    g.add_edge(TopologyEdge("n0", "n1"))
    g.add_edge(TopologyEdge("n1", "n2"))
    hist = g.depth_histogram()
    assert "0" in hist  # n0 at depth 0
    assert "1" in hist  # n1 at depth 1
    assert "2" in hist  # n2 at depth 2


def test_to_dict_structure():
    g = TopologyGraph()
    g.add_node(_node("x"))
    g.add_node(_node("y"))
    g.add_edge(TopologyEdge("x", "y"))
    d = g.to_dict()
    assert "nodes" in d
    assert "edges" in d
    assert len(d["nodes"]) == 2
    assert len(d["edges"]) == 1


def test_clear():
    g = TopologyGraph()
    g.add_node(_node("n1"))
    g.clear()
    assert g.nodes() == []
