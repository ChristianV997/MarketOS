"""vector_adapter — emit vector store events into the observability layer."""
from __future__ import annotations

import time
from typing import Any


def emit_indexed(collection: str, count: int = 1) -> None:
    try:
        from ..telemetry_router import get_telemetry_router
        get_telemetry_router().record_vector_indexed(collection, count)
    except Exception:
        pass


def emit_searched(collection: str, latency_ms: float) -> None:
    try:
        from ..telemetry_router import get_telemetry_router
        get_telemetry_router().record_vector_searched(collection, latency_ms)
    except Exception:
        pass


def emit_store_size(collection: str, size: int) -> None:
    try:
        from ..metrics import vector_store_size
        vector_store_size.labels(collection=collection).set(size)
    except Exception:
        pass


def vector_summary(workspace: str = "default") -> dict[str, Any]:
    """Return collection sizes for all known collections."""
    try:
        from backend.vector.qdrant_client import get_store
        from backend.vector.collections import ALL_COLLECTIONS
        store = get_store()
        return {
            "workspace": workspace,
            "collections": {c: store.count(c) for c in ALL_COLLECTIONS},
            "ts": time.time(),
        }
    except Exception:
        return {"workspace": workspace, "collections": {}, "ts": time.time()}
