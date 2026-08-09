"""backend.events.log — append-only event log public API.

Provides a clean interface over RuntimeReplayStore for any subsystem that
needs to write or read from the durable event log without depending on the
broker pub/sub path.

Use cases:
  - Lineage tracker writing causal records
  - Sleep/consolidation runtime reading event windows
  - Artifact registry writing lifecycle events
  - Replay validation scanning past events
"""
from __future__ import annotations

import time
import uuid
from typing import Any


def _store():
    try:
        from backend.runtime.replay_store import get_replay_store
        return get_replay_store()
    except Exception:
        return None


def append(
    event_type: str,
    payload: dict[str, Any],
    source: str = "",
    correlation_id: str | None = None,
    sequence_id: int | None = None,
) -> str:
    """Append a raw event to the durable log without publishing to subscribers.

    Returns the generated event_id.  Fails silently if the store is
    unavailable (never raises).
    """
    event_id = uuid.uuid4().hex[:12]
    store = _store()
    if store is None:
        return event_id
    try:
        from backend.pubsub.broker import EventEnvelope
        env = EventEnvelope(
            event_id=event_id,
            type=event_type,
            ts=time.time(),
            source=source,
            payload=payload,
            correlation_id=correlation_id,
            sequence_id=sequence_id,
        )
        store.append(env)
    except Exception:
        try:
            from backend.observability.metrics import event_log_write_failures_total
            event_log_write_failures_total.labels(backend="replay_store").inc()
        except Exception:
            pass
    return event_id


def tail(
    n: int = 100,
    event_type: str | None = None,
    since_ts: float | None = None,
) -> list[dict[str, Any]]:
    """Return the last *n* events, optionally filtered by type or timestamp."""
    store = _store()
    if store is None:
        return []
    try:
        rows = store.tail(n)
        if event_type:
            rows = [r for r in rows if r.get("type") == event_type]
        if since_ts is not None:
            rows = [r for r in rows if r.get("ts", 0.0) >= since_ts]
        return rows
    except Exception:
        return []


def scan_window(
    start_ts: float,
    end_ts: float,
    event_type: str | None = None,
) -> list[dict[str, Any]]:
    """Return events in [start_ts, end_ts] from the replay store."""
    store = _store()
    if store is None:
        return []
    try:
        all_rows = store.tail(5000)
        rows = [
            r for r in all_rows
            if start_ts <= r.get("ts", 0.0) <= end_ts
        ]
        if event_type:
            rows = [r for r in rows if r.get("type") == event_type]
        return rows
    except Exception:
        return []
