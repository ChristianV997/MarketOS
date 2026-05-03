"""Tests for topology_diff."""
from backend.runtime.topology.topology_diff import diff_snapshots


def _snap(nodes: list[dict]) -> dict:
    return {"nodes": nodes, "edges": []}


def test_diff_added():
    before = _snap([{"node_id": "a", "node_type": "semantic"}])
    after  = _snap([{"node_id": "a", "node_type": "semantic"}, {"node_id": "b", "node_type": "semantic"}])
    d = diff_snapshots(before, after)
    assert d["added_count"] == 1
    assert "b" in d["added_ids"]


def test_diff_removed():
    before = _snap([{"node_id": "a", "node_type": "semantic"}, {"node_id": "b", "node_type": "semantic"}])
    after  = _snap([{"node_id": "a", "node_type": "semantic"}])
    d = diff_snapshots(before, after)
    assert d["removed_count"] == 1
    assert "b" in d["removed_ids"]


def test_diff_type_delta():
    before = _snap([{"node_id": "a", "node_type": "semantic"}])
    after  = _snap([{"node_id": "a", "node_type": "semantic"}, {"node_id": "b", "node_type": "lineage"}])
    d = diff_snapshots(before, after)
    assert d["type_deltas"]["lineage"] == 1
    assert d["type_deltas"]["semantic"] == 0


def test_diff_no_change():
    snap = _snap([{"node_id": "a", "node_type": "semantic"}])
    d = diff_snapshots(snap, snap)
    assert d["added_count"] == 0
    assert d["removed_count"] == 0
