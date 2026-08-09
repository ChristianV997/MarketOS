"""EpisodicStore — raw event and execution history log.

Episodic memory is the lowest-level, highest-fidelity memory tier.
It stores every event, decision, and outcome exactly as it occurred —
no compression, no clustering.

The episodic store is bounded by ``MAX_EPISODES`` to prevent unbounded growth.
Older episodes are pruned (FIFO) when the limit is reached.  For durable
episodic storage, the RuntimeReplayStore (DuckDB) is the canonical log;
this is the fast in-process index.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any


MAX_EPISODES = int(__import__("os").getenv("EPISODIC_MAX_EPISODES", "10000"))


class Episode:
    """One episodic memory unit: a single event or execution outcome."""
    __slots__ = ("episode_id", "event_type", "ts", "payload", "source",
                 "workspace", "parent_episode_id")

    def __init__(
        self,
        episode_id:       str,
        event_type:       str,
        ts:               float,
        payload:          dict[str, Any],
        source:           str = "",
        workspace:        str = "default",
        parent_episode_id: str = "",
    ) -> None:
        self.episode_id        = episode_id
        self.event_type        = event_type
        self.ts                = ts
        self.payload           = payload
        self.source            = source
        self.workspace         = workspace
        self.parent_episode_id = parent_episode_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode_id":        self.episode_id,
            "event_type":        self.event_type,
            "ts":                self.ts,
            "payload":           self.payload,
            "source":            self.source,
            "workspace":         self.workspace,
            "parent_episode_id": self.parent_episode_id,
        }


class EpisodicStore:
    """Bounded FIFO store of Episode objects with type and workspace indexes."""

    def __init__(self, max_episodes: int = MAX_EPISODES) -> None:
        self._max      = max_episodes
        self._lock     = threading.Lock()
        self._episodes: deque[Episode] = deque(maxlen=max_episodes)

    def record(self, episode: Episode) -> None:
        with self._lock:
            self._episodes.append(episode)

    def record_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        source: str = "",
        workspace: str = "default",
        parent_episode_id: str = "",
    ) -> str:
        import uuid
        eid = uuid.uuid4().hex[:12]
        self.record(Episode(
            episode_id=eid,
            event_type=event_type,
            ts=time.time(),
            payload=payload,
            source=source,
            workspace=workspace,
            parent_episode_id=parent_episode_id,
        ))
        return eid

    def tail(self, n: int = 100) -> list[Episode]:
        with self._lock:
            return list(self._episodes)[-n:]

    def by_type(self, event_type: str, limit: int = 500) -> list[Episode]:
        # Derived from the bounded deque so no secondary index can grow
        # unbounded as old episodes are evicted.
        with self._lock:
            matches = [e for e in self._episodes if e.event_type == event_type]
        return matches[-limit:]

    def by_workspace(self, workspace: str, limit: int = 500) -> list[Episode]:
        with self._lock:
            matches = [e for e in self._episodes if e.workspace == workspace]
        return matches[-limit:]

    def count(self) -> int:
        with self._lock:
            return len(self._episodes)

    def window(self, start_ts: float, end_ts: float) -> list[Episode]:
        with self._lock:
            return [e for e in self._episodes if start_ts <= e.ts <= end_ts]

    # ── persistence ─────────────────────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-safe snapshot of all episodes (newest last)."""
        with self._lock:
            return {"episodes": [e.to_dict() for e in self._episodes]}

    def restore(self, data: dict[str, Any]) -> None:
        """Rebuild the store from a snapshot produced by ``snapshot()``."""
        rows = data.get("episodes", []) if isinstance(data, dict) else []
        with self._lock:
            self._episodes.clear()
            for d in rows:
                try:
                    self._episodes.append(Episode(
                        episode_id=d["episode_id"],
                        event_type=d.get("event_type", ""),
                        ts=d.get("ts", 0.0),
                        payload=d.get("payload", {}),
                        source=d.get("source", ""),
                        workspace=d.get("workspace", "default"),
                        parent_episode_id=d.get("parent_episode_id", ""),
                    ))
                except Exception:
                    continue
