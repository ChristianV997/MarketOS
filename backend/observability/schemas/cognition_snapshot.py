"""CognitionSnapshot — point-in-time state of the cognitive infrastructure."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CognitionSnapshot:
    """Immutable snapshot of the full cognitive system state.

    Captured periodically or on-demand for comparison, diffing,
    and topology visualization.  Never mutates existing state.
    """
    snapshot_id:      str
    captured_at:      float = field(default_factory=time.time)
    workspace:        str   = "default"

    # Memory tiers
    episodic_count:   int   = 0
    semantic_count:   int   = 0
    semantic_generation: int = 0
    procedural_count: int   = 0

    # Vector layer
    vector_counts:    dict[str, int]   = field(default_factory=dict)  # collection → count

    # Lineage
    lineage_node_count: int   = 0
    worldline_count:    int   = 0

    # Replay
    replay_event_count: int   = 0
    last_cycle_ts:      float = 0.0
    cycle_count:        int   = 0

    # Entropy indicators
    semantic_duplication_rate: float = 0.0
    lineage_depth_max:         int   = 0
    vector_fragmentation:      float = 0.0

    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def capture(cls, workspace: str = "default") -> "CognitionSnapshot":
        """Capture current state from all live singletons."""
        snap = cls(
            snapshot_id=uuid.uuid4().hex[:12],
            workspace=workspace,
        )
        _fill_memory(snap)
        _fill_vector(snap)
        _fill_lineage(snap)
        _fill_replay(snap)
        _fill_entropy(snap)
        return snap

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id":             self.snapshot_id,
            "captured_at":             self.captured_at,
            "workspace":               self.workspace,
            "episodic_count":          self.episodic_count,
            "semantic_count":          self.semantic_count,
            "semantic_generation":     self.semantic_generation,
            "procedural_count":        self.procedural_count,
            "vector_counts":           self.vector_counts,
            "lineage_node_count":      self.lineage_node_count,
            "worldline_count":         self.worldline_count,
            "replay_event_count":      self.replay_event_count,
            "last_cycle_ts":           self.last_cycle_ts,
            "cycle_count":             self.cycle_count,
            "semantic_duplication_rate": self.semantic_duplication_rate,
            "lineage_depth_max":       self.lineage_depth_max,
            "vector_fragmentation":    self.vector_fragmentation,
            "metadata":                self.metadata,
        }


# ── capture helpers ───────────────────────────────────────────────────────────

def _fill_memory(snap: CognitionSnapshot) -> None:
    try:
        from backend.memory.episodic   import get_episodic_store
        from backend.memory.semantic   import get_semantic_store
        from backend.memory.procedural import get_procedural_store
        snap.episodic_count      = get_episodic_store().count()
        snap.semantic_count      = get_semantic_store().count()
        snap.semantic_generation = get_semantic_store().generation()
        snap.procedural_count    = get_procedural_store().count()
    except Exception:
        pass


def _fill_vector(snap: CognitionSnapshot) -> None:
    try:
        from backend.vector.qdrant_client import get_store
        from backend.vector.collections   import ALL_COLLECTIONS
        store = get_store()
        snap.vector_counts = {c: store.count(c) for c in ALL_COLLECTIONS}
    except Exception:
        pass


def _fill_lineage(snap: CognitionSnapshot) -> None:
    try:
        from backend.lineage import get_tracker
        t = get_tracker()
        snap.lineage_node_count = t.node_count()
        snap.worldline_count    = t.worldline_count()
    except Exception:
        pass


def _fill_replay(snap: CognitionSnapshot) -> None:
    try:
        from backend.runtime.replay_store import get_replay_store
        snap.replay_event_count = get_replay_store().count()
    except Exception:
        pass
    try:
        from backend.runtime.sleep.replay_scheduler import get_scheduler
        s = get_scheduler()
        st = s.status()
        snap.cycle_count    = st.get("cycle_count", 0)
        snap.last_cycle_ts  = st.get("last_cycle_ts", 0.0)
    except Exception:
        pass


def _fill_entropy(snap: CognitionSnapshot) -> None:
    try:
        from backend.memory.semantic import get_semantic_store
        store  = get_semantic_store()
        total  = store.count()
        # Duplication proxy: ratio of units to generation
        gen    = max(store.generation(), 1)
        snap.semantic_duplication_rate = round(total / gen, 3)
    except Exception:
        pass
    try:
        from backend.lineage import get_tracker
        graph = get_tracker().graph()
        nodes = graph.all_nodes()
        if nodes:
            depths = [len(graph.lineage_chain(n.node_id)) for n in nodes[:50]]
            snap.lineage_depth_max = max(depths) if depths else 0
    except Exception:
        pass
