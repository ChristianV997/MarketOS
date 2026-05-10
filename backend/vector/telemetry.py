"""backend.vector.telemetry — vector-layer event emission."""
from __future__ import annotations

import logging
import time

log = logging.getLogger(__name__)

_VECTOR_INDEXED  = "vector.indexed"
_VECTOR_SEARCHED = "vector.searched"
_CLUSTER_UPDATED = "vector.cluster.updated"


def _broker():
    try:
        from backend.pubsub.broker import get_broker
        return get_broker()
    except Exception:
        return None


def emit_indexed(collection: str, count: int, source: str = "") -> None:
    b = _broker()
    if b is None:
        return
    try:
        b.publish(
            _VECTOR_INDEXED,
            {
                "type": _VECTOR_INDEXED,
                "collection": collection,
                "count": count,
                "ts": time.time(),
            },
            source=source or "vector",
        )
    except Exception as exc:
        log.debug("vector telemetry emit_indexed failed: %s", exc)


def emit_searched(
    collection: str,
    result_count: int,
    top_score: float = 0.0,
    sequence_id: str = "",
) -> None:
    b = _broker()
    if b is None:
        return
    try:
        b.publish(
            _VECTOR_SEARCHED,
            {
                "type": _VECTOR_SEARCHED,
                "collection": collection,
                "result_count": result_count,
                "top_score": top_score,
                "sequence_id": sequence_id,
                "ts": time.time(),
            },
            source="vector",
        )
    except Exception as exc:
        log.debug("vector telemetry emit_searched failed: %s", exc)


def emit_cluster_updated(collection: str, k: int, source: str = "") -> None:
    b = _broker()
    if b is None:
        return
    try:
        b.publish(
            _CLUSTER_UPDATED,
            {
                "type": _CLUSTER_UPDATED,
                "collection": collection,
                "k": k,
                "ts": time.time(),
            },
            source=source or "vector",
        )
    except Exception as exc:
        log.debug("vector telemetry emit_cluster_updated failed: %s", exc)
