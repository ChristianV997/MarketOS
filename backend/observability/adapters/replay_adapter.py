"""replay_adapter — bridge replay store events into observability."""
from __future__ import annotations

import time
from typing import Any


def emit_event_published(event_type: str) -> None:
    try:
        from ..telemetry_router import get_telemetry_router
        get_telemetry_router().record_event_published(event_type)
    except Exception:
        pass


def emit_replay_store_size() -> None:
    try:
        from backend.runtime.replay_store import get_replay_store
        from ..metrics import replay_store_size
        replay_store_size.set(get_replay_store().count())
    except Exception:
        pass


def replay_summary(n: int = 10) -> dict[str, Any]:
    """Return recent replay store entries."""
    try:
        from backend.runtime.replay_store import get_replay_store
        store = get_replay_store()
        rows = store.recent(n)
        return {
            "count": store.count(),
            "recent": rows,
            "ts": time.time(),
        }
    except Exception:
        return {"count": 0, "recent": [], "ts": time.time()}
