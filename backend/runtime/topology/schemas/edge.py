"""topology.schemas.edge — directed edge in the topology graph."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TopologyEdge:
    source_id: str
    target_id: str
    edge_type: str = "causal"   # "causal" | "semantic" | "replay" | "lineage"
    weight: float = 1.0
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "edge_type": self.edge_type,
            "weight": self.weight,
            "ts": self.ts,
        }
