"""TopologyState — the current structural state of the cognitive topology."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TopologyState:
    """Point-in-time structural state of the cognitive topology.

    Used for snapshot diffing and drift detection — not for live monitoring.
    """
    state_id:    str
    captured_at: float = field(default_factory=time.time)
    workspace:   str   = "default"

    node_types:  dict[str, int] = field(default_factory=dict)  # type → count
    edge_count:  int = 0
    depth_histogram: dict[str, int] = field(default_factory=dict)  # depth → count
    cluster_count:   int = 0
    workspace_node_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state_id":    self.state_id,
            "captured_at": self.captured_at,
            "workspace":   self.workspace,
            "node_types":  self.node_types,
            "edge_count":  self.edge_count,
            "depth_histogram": self.depth_histogram,
            "cluster_count":   self.cluster_count,
            "workspace_node_counts": self.workspace_node_counts,
        }
