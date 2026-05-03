"""topology.schemas.node — typed topology node."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TopologyNode:
    node_id: str
    node_type: str        # "episodic" | "semantic" | "procedural" | "vector" | "lineage" | "trace"
    workspace: str = "default"
    label: str = ""
    score: float = 0.0
    ts: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "workspace": self.workspace,
            "label": self.label,
            "score": self.score,
            "ts": self.ts,
            "metadata": self.metadata,
        }
