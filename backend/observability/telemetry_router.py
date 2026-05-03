"""telemetry_router — single ingestion point for all observability events.

All subsystems route their telemetry through here instead of calling
Prometheus / event-log directly.  This keeps telemetry coupling at one
call site and allows future backend swaps (e.g. OTel exporter).
"""
from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger(__name__)


class TelemetryRouter:
    """Routes telemetry to Prometheus metrics + event log + trace registry."""

    def record_event_published(self, event_type: str) -> None:
        try:
            from .metrics import events_published_total
            events_published_total.labels(event_type=event_type).inc()
        except Exception:
            pass

    def record_vector_indexed(self, collection: str, count: int) -> None:
        try:
            from .metrics import vector_indexed_total, vector_store_size
            vector_indexed_total.labels(collection=collection).inc(count)
        except Exception:
            pass

    def record_vector_searched(self, collection: str, latency_ms: float) -> None:
        try:
            from .metrics import vector_searched_total, vector_search_latency_ms
            vector_searched_total.labels(collection=collection).inc()
            vector_search_latency_ms.labels(collection=collection).observe(latency_ms)
        except Exception:
            pass

    def record_sleep_cycle(self, duration_ms: float, compression_ratio: float,
                            units_created: int) -> None:
        try:
            from .metrics import (sleep_cycles_total, sleep_cycle_duration_ms,
                                   sleep_compression_ratio, sleep_units_created)
            sleep_cycles_total.inc()
            sleep_cycle_duration_ms.observe(duration_ms)
            sleep_compression_ratio.set(compression_ratio)
            sleep_units_created.inc(units_created)
        except Exception:
            pass

    def record_inference(self, provider: str, status: str, latency_ms: float) -> None:
        try:
            from .metrics import inference_requests_total, inference_latency_ms
            inference_requests_total.labels(provider=provider, status=status).inc()
            inference_latency_ms.labels(provider=provider).observe(latency_ms)
        except Exception:
            pass

    def record_trace_span(self, name: str, status: str, duration_ms: float) -> None:
        try:
            from .metrics import trace_spans_total, trace_duration_ms
            trace_spans_total.labels(name=name, status=status).inc()
            trace_duration_ms.labels(name=name).observe(duration_ms)
        except Exception:
            pass

    def update_memory_gauges(self) -> None:
        """Refresh all gauge metrics from live singletons."""
        try:
            from backend.memory.episodic   import get_episodic_store
            from backend.memory.semantic   import get_semantic_store
            from backend.memory.procedural import get_procedural_store
            from .metrics import (episodic_count, semantic_count,
                                   semantic_generation, procedural_count)
            episodic_count.set(get_episodic_store().count())
            sem   = get_semantic_store()
            semantic_generation.set(sem.generation())
            for domain in ["hook", "angle", "signal", "product"]:
                semantic_count.labels(domain=domain).set(sem.count(domain))
            procedural_count.set(get_procedural_store().count())
        except Exception:
            pass

    def update_lineage_gauges(self) -> None:
        try:
            from backend.lineage import get_tracker
            from .metrics import lineage_nodes_total, lineage_worldlines_total
            t = get_tracker()
            lineage_nodes_total.set(t.node_count())
            lineage_worldlines_total.set(t.worldline_count())
        except Exception:
            pass

    def snapshot(self) -> dict[str, Any]:
        """Capture CognitionSnapshot and return as dict."""
        from .schemas.cognition_snapshot import CognitionSnapshot
        return CognitionSnapshot.capture().to_dict()

    def entropy_report(self, workspace: str = "default") -> dict[str, Any]:
        """Measure and return entropy report as dict."""
        from .entropy_metrics import measure_entropy
        return measure_entropy(workspace=workspace).to_dict()


_router: TelemetryRouter | None = None

import threading
_lock = threading.Lock()


def get_telemetry_router() -> TelemetryRouter:
    global _router
    if _router is None:
        with _lock:
            if _router is None:
                _router = TelemetryRouter()
    return _router
