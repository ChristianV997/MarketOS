"""LineageTracker — singleton that records all artifact and event lineage.

Every system that produces an artifact or emits a causal event calls
``track()`` to register the node in the global graph.  The tracker also
maintains Worldlines for long-running computational threads.
"""
from __future__ import annotations

import threading
import time
import uuid

from .node      import LineageNode
from .graph     import LineageGraph
from .worldline import Worldline


class LineageTracker:
    """Thread-safe global lineage tracker.

    Usage::

        from backend.lineage.tracker import get_tracker

        tracker = get_tracker()
        node_id = tracker.track(
            node_type="campaign",
            label="cid_abc123",
            parent_ids=["playbook_xyz"],
            workspace="prod",
            source="orchestrator",
            payload=artifact.to_dict(),
        )
    """

    def __init__(self) -> None:
        self._graph:      LineageGraph              = LineageGraph()
        self._worldlines: dict[str, Worldline]      = {}
        self._lock:       threading.Lock            = threading.Lock()

    # ── node registration ─────────────────────────────────────────────────────

    def track(
        self,
        node_type:  str,
        label:      str = "",
        parent_ids: list[str] | None = None,
        workspace:  str = "default",
        source:     str = "",
        node_id:    str = "",
        payload:    dict | None = None,
    ) -> str:
        """Register a node and return its node_id."""
        nid  = node_id or uuid.uuid4().hex[:16]
        node = LineageNode(
            node_id=nid,
            node_type=node_type,
            label=label,
            ts=time.time(),
            parent_ids=parent_ids or [],
            workspace=workspace,
            source=source,
            payload=payload or {},
        )
        self._graph.add_node(node)

        # Append to durable log (fail-silent)
        try:
            from backend.events.log import append
            append(
                "lineage.node.tracked",
                payload=node.to_dict(),
                source="lineage_tracker",
            )
        except Exception:
            pass

        return nid

    def track_artifact(self, artifact: "BaseArtifact") -> str:  # type: ignore[name-defined]
        """Convenience wrapper: track any BaseArtifact subclass."""
        return self.track(
            node_id=artifact.artifact_id,
            node_type=artifact.artifact_type,
            label=getattr(artifact, "label", "") or artifact.artifact_id[:12],
            parent_ids=artifact.parent_ids,
            workspace=artifact.workspace,
            source=getattr(artifact, "source_repo", "marketos"),
            payload=artifact.to_dict(),
        )

    # ── worldline management ──────────────────────────────────────────────────

    def start_worldline(
        self,
        worldline_id: str = "",
        label: str = "",
        workspace: str = "default",
        forked_from: str = "",
    ) -> str:
        wid = worldline_id or uuid.uuid4().hex[:12]
        with self._lock:
            self._worldlines[wid] = Worldline(
                worldline_id=wid,
                label=label,
                workspace=workspace,
                forked_from=forked_from,
            )
        return wid

    def append_to_worldline(self, worldline_id: str, node_id: str) -> None:
        node = self._graph.get(node_id)
        if node is None:
            return
        with self._lock:
            wl = self._worldlines.get(worldline_id)
            if wl:
                wl.append_step(node)

    def terminate_worldline(self, worldline_id: str) -> None:
        with self._lock:
            wl = self._worldlines.get(worldline_id)
            if wl:
                wl.terminate()

    def get_worldline(self, worldline_id: str) -> Worldline | None:
        with self._lock:
            return self._worldlines.get(worldline_id)

    # ── graph queries ─────────────────────────────────────────────────────────

    def ancestors(self, node_id: str, depth: int = 20) -> list[LineageNode]:
        return self._graph.ancestors(node_id, depth=depth)

    def descendants(self, node_id: str, depth: int = 20) -> list[LineageNode]:
        return self._graph.descendants(node_id, depth=depth)

    def lineage_chain(self, node_id: str) -> list[str]:
        return self._graph.lineage_chain(node_id)

    def graph(self) -> LineageGraph:
        return self._graph

    def node_count(self) -> int:
        return self._graph.count()

    def worldline_count(self) -> int:
        with self._lock:
            return len(self._worldlines)

    # ── persistence ─────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        """Return a JSON-safe snapshot of the lineage graph."""
        return {"nodes": self._graph.snapshot()}

    def restore(self, data: dict) -> None:
        """Rebuild the lineage graph from a snapshot."""
        if isinstance(data, dict):
            self._graph.restore(data.get("nodes", []))


_tracker: LineageTracker | None = None
_tracker_lock = threading.Lock()

from backend.core.persistence import save_json_atomic, load_json, state_path

_LINEAGE_PATH = state_path("lineage.json")


def get_tracker() -> LineageTracker:
    global _tracker
    if _tracker is None:
        with _tracker_lock:
            if _tracker is None:
                tracker = LineageTracker()
                data = load_json(_LINEAGE_PATH)
                if data:
                    tracker.restore(data)
                _tracker = tracker
    return _tracker


def persist_lineage() -> bool:
    """Write the current lineage graph to disk (best-effort)."""
    return save_json_atomic(_LINEAGE_PATH, get_tracker().snapshot())
