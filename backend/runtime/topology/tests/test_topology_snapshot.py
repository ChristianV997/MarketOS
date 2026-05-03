"""Tests for topology_snapshot."""
from backend.runtime.topology.topology_snapshot import capture_topology_snapshot, TopologySnapshot


def test_capture_returns_snapshot():
    s = capture_topology_snapshot(workspace="test")
    assert isinstance(s, TopologySnapshot)


def test_snapshot_has_id():
    s = capture_topology_snapshot()
    assert s.snapshot_id
    assert len(s.snapshot_id) > 0


def test_snapshot_workspace():
    s = capture_topology_snapshot(workspace="myws")
    assert s.workspace == "myws"


def test_snapshot_to_dict_keys():
    s = capture_topology_snapshot()
    d = s.to_dict()
    for key in ("snapshot_id", "workspace", "ts", "node_types", "total_nodes", "total_edges"):
        assert key in d


def test_snapshot_node_types_is_dict():
    s = capture_topology_snapshot()
    assert isinstance(s.node_types, dict)


def test_snapshot_ts_recent():
    import time
    s = capture_topology_snapshot()
    assert s.ts > time.time() - 5


def test_snapshot_nodes_edges_lists():
    s = capture_topology_snapshot()
    assert isinstance(s.nodes, list)
    assert isinstance(s.edges, list)
