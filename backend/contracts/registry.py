"""ArtifactRegistry — in-memory artifact catalog with lineage tracking.

Provides a thread-safe append-only store of all typed artifacts produced
during a runtime session.  On restart the registry is rebuilt from the
durable event log (ReplayArtifact events).
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any, Type

_log = logging.getLogger(__name__)

# Default replay-hydration cap, overridable via env var. Previously fixed
# at 5000 with no visibility when it truncated — a restart with more than
# this many historical artifact-registration events silently lost the
# older ones. Now configurable and the truncation case is logged (see
# hydrate_from_replay below) instead of failing silently.
_DEFAULT_REPLAY_LIMIT = int(os.getenv("ARTIFACT_REPLAY_LIMIT", "5000"))

from .base        import BaseArtifact
from .simulation  import SimulationArtifact
from .research    import ResearchArtifact
from .workflow    import WorkflowArtifact
from .semantic    import SemanticAsset
from .campaign    import CampaignAsset
from .replay      import ReplayArtifact


_TYPE_MAP: dict[str, Type[BaseArtifact]] = {
    "simulation": SimulationArtifact,
    "research":   ResearchArtifact,
    "workflow":   WorkflowArtifact,
    "semantic":   SemanticAsset,
    "campaign":   CampaignAsset,
    "replay":     ReplayArtifact,
    "base":       BaseArtifact,
}


class ArtifactRegistry:
    """Thread-safe in-memory store of all produced artifacts."""

    def __init__(self) -> None:
        self._lock:      threading.Lock        = threading.Lock()
        self._store:     dict[str, BaseArtifact] = {}
        self._by_type:   dict[str, list[str]]  = {}  # type → [artifact_id]
        self._by_parent: dict[str, list[str]]  = {}  # parent_id → [child_id]

    def _register_in_memory(self, artifact: BaseArtifact) -> None:
        """Store one artifact and update indexes. Caller holds ``_lock``."""
        previous = self._store.get(artifact.artifact_id)
        if previous is not None:
            # Updates replace index entries rather than multiplying them.
            previous_type_ids = self._by_type.get(previous.artifact_type, [])
            self._by_type[previous.artifact_type] = [
                item_id for item_id in previous_type_ids
                if item_id != artifact.artifact_id
            ]
            for parent_id in previous.parent_ids:
                parent_children = self._by_parent.get(parent_id, [])
                retained = [
                    child_id for child_id in parent_children
                    if child_id != artifact.artifact_id
                ]
                if retained:
                    self._by_parent[parent_id] = retained
                else:
                    self._by_parent.pop(parent_id, None)
        self._store[artifact.artifact_id] = artifact
        self._by_type.setdefault(artifact.artifact_type, []).append(artifact.artifact_id)
        for pid in artifact.parent_ids:
            self._by_parent.setdefault(pid, []).append(artifact.artifact_id)

    def register(self, artifact: BaseArtifact) -> None:
        """Store artifact and update indexes. Emits an event to the log."""
        with self._lock:
            self._register_in_memory(artifact)

        # Append to durable log (fail-silent)
        try:
            from backend.events.log import append
            append(
                f"artifact.{artifact.artifact_type}.registered",
                payload=artifact.to_dict(),
                source="artifact_registry",
            )
        except Exception:
            pass

    def hydrate(self, events: list[dict[str, Any]]) -> int:
        """Rebuild the registry from ordered artifact-registration events.

        Hydration is deliberately side-effect free: restored entries must not
        emit another copy of historical events. Later events with the same id
        replace earlier versions, preserving the latest campaign outcome.
        """
        restored = 0
        with self._lock:
            for event in events:
                payload = event.get("payload", event)
                if not isinstance(payload, dict) or not payload.get("artifact_id"):
                    continue
                event_type = str(event.get("type", ""))
                if event_type and not (event_type.startswith("artifact.") and event_type.endswith(".registered")):
                    continue
                try:
                    self._register_in_memory(self.deserialize(payload))
                    restored += 1
                except Exception:
                    continue
        return restored

    def hydrate_from_replay(self, limit: int | None = None) -> int:
        """Restore retained artifacts from the configured durable replay store.

        ``limit`` defaults to ARTIFACT_REPLAY_LIMIT (env-configurable,
        5000 unless overridden). If the replay log actually has at least
        that many events, hydration may be truncating older artifacts —
        this is now logged as a warning (previously silent) so an
        operator seeing missing artifacts after restart has a concrete
        signal to look at, rather than an artifact that simply "never
        existed."
        """
        effective_limit = _DEFAULT_REPLAY_LIMIT if limit is None else limit
        try:
            from backend.events.log import tail
            events = tail(effective_limit)
            if len(events) >= effective_limit:
                _log.warning(
                    "artifact_registry_hydration_may_be_truncated "
                    "limit=%s returned=%s — older artifacts may be missing; "
                    "raise ARTIFACT_REPLAY_LIMIT if this is unexpected",
                    effective_limit, len(events),
                )
            return self.hydrate(events)
        except Exception:
            return 0

    def get(self, artifact_id: str) -> BaseArtifact | None:
        with self._lock:
            return self._store.get(artifact_id)

    def by_type(self, artifact_type: str) -> list[BaseArtifact]:
        with self._lock:
            ids = self._by_type.get(artifact_type, [])
            return [self._store[i] for i in ids if i in self._store]

    def children_of(self, parent_id: str) -> list[BaseArtifact]:
        with self._lock:
            ids = self._by_parent.get(parent_id, [])
            return [self._store[i] for i in ids if i in self._store]

    def count(self, artifact_type: str | None = None) -> int:
        with self._lock:
            if artifact_type:
                return len(self._by_type.get(artifact_type, []))
            return len(self._store)

    def deserialize(self, d: dict[str, Any]) -> BaseArtifact:
        """Reconstruct a typed artifact from its dict representation."""
        atype = d.get("artifact_type", "base")
        cls   = _TYPE_MAP.get(atype)
        if cls is None and atype == "commercial_run_envelope":
            # Lazy import (mirrors register()'s own backend.events.log
            # import below) — backend.experiments imports backend.contracts
            # at module scope, so importing it back here at module load
            # time would be circular; importing lazily inside this method
            # is safe since both packages are fully initialized by call time.
            try:
                from backend.experiments.envelope import CommercialRunEnvelope
                cls = CommercialRunEnvelope
            except Exception:
                cls = None
        cls = cls or BaseArtifact
        return cls.from_dict(d)


_registry: ArtifactRegistry | None = None
_registry_lock = threading.Lock()


def get_registry() -> ArtifactRegistry:
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = ArtifactRegistry()
    return _registry
