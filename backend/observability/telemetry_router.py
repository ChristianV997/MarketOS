"""telemetry_router — single ingestion point for all observability events.

All subsystems route their telemetry through here instead of calling
Prometheus / event-log directly.  This keeps telemetry coupling at one
call site and allows future backend swaps (e.g. OTel exporter).
"""
from __future__ import annotations

import logging
import threading
from typing import Any

log = logging.getLogger(__name__)


class TelemetryRouter:
    """Routes telemetry to Prometheus metrics + event log + trace registry.

    All labels are normalized and bounded to safe canonical sets or fallback
    buckets ('other' / 'unknown') to prevent cardinality explosions and secret leaks.
    All measurements are validated to be finite and non-negative (where required)
    to protect Prometheus state from NaN poisoning or crashes.
    """

    def record_event_published(self, event_type: str) -> None:
        try:
            from .metrics import events_published_total, normalize_label
            safe_type = normalize_label("event_type", event_type)
            events_published_total.labels(event_type=safe_type).inc()
        except Exception:
            pass

    def record_vector_indexed(self, collection: str, count: int) -> None:
        try:
            from .metrics import (
                vector_indexed_total,
                normalize_label,
                validate_int_measurement,
            )
            safe_col = normalize_label("collection", collection)
            valid_count = validate_int_measurement(count, non_negative=True)
            if valid_count is None:
                log.warning(
                    "telemetry_router: invalid vector_indexed count %r for collection %r (dropped)",
                    count,
                    safe_col,
                )
                return
            vector_indexed_total.labels(collection=safe_col).inc(valid_count)
        except Exception:
            pass

    def record_vector_searched(self, collection: str, latency_ms: float) -> None:
        try:
            from .metrics import (
                vector_searched_total,
                vector_search_latency_ms,
                normalize_label,
                validate_measurement,
            )
            safe_col = normalize_label("collection", collection)
            vector_searched_total.labels(collection=safe_col).inc()
            valid_lat = validate_measurement(latency_ms, non_negative=True)
            if valid_lat is not None:
                vector_search_latency_ms.labels(collection=safe_col).observe(valid_lat)
            else:
                log.warning(
                    "telemetry_router: invalid vector_searched latency_ms %r for collection %r (dropped observation)",
                    latency_ms,
                    safe_col,
                )
        except Exception:
            pass

    def record_sleep_cycle(
        self, duration_ms: float, compression_ratio: float, units_created: int
    ) -> None:
        try:
            from .metrics import (
                sleep_cycles_total,
                sleep_cycle_duration_ms,
                sleep_compression_ratio,
                sleep_units_created,
                validate_measurement,
                validate_int_measurement,
            )
            sleep_cycles_total.inc()
            valid_dur = validate_measurement(duration_ms, non_negative=True)
            if valid_dur is not None:
                sleep_cycle_duration_ms.observe(valid_dur)
            else:
                log.warning(
                    "telemetry_router: invalid sleep_cycle duration_ms %r (dropped observation)",
                    duration_ms,
                )

            valid_comp = validate_measurement(compression_ratio, non_negative=False)
            if valid_comp is not None:
                sleep_compression_ratio.set(valid_comp)
            else:
                log.warning(
                    "telemetry_router: invalid sleep_cycle compression_ratio %r (dropped set)",
                    compression_ratio,
                )

            valid_units = validate_int_measurement(units_created, non_negative=True)
            if valid_units is not None:
                sleep_units_created.inc(valid_units)
            else:
                log.warning(
                    "telemetry_router: invalid sleep_cycle units_created %r (dropped inc)",
                    units_created,
                )
        except Exception:
            pass

    def record_inference(self, provider: str, status: str, latency_ms: float) -> None:
        try:
            from .metrics import (
                inference_requests_total,
                inference_latency_ms,
                normalize_label,
                validate_measurement,
            )
            safe_provider = normalize_label("provider", provider)
            safe_status = normalize_label("status", status)
            inference_requests_total.labels(
                provider=safe_provider, status=safe_status
            ).inc()
            valid_lat = validate_measurement(latency_ms, non_negative=True)
            if valid_lat is not None:
                inference_latency_ms.labels(provider=safe_provider).observe(valid_lat)
            else:
                log.warning(
                    "telemetry_router: invalid inference latency_ms %r for provider %r (dropped observation)",
                    latency_ms,
                    safe_provider,
                )
        except Exception:
            pass

    def record_trace_span(self, name: str, status: str, duration_ms: float) -> None:
        try:
            from .metrics import (
                trace_spans_total,
                trace_duration_ms,
                normalize_label,
                validate_measurement,
            )
            safe_name = normalize_label("name", name)
            safe_status = normalize_label("status", status)
            trace_spans_total.labels(name=safe_name, status=safe_status).inc()
            valid_dur = validate_measurement(duration_ms, non_negative=True)
            if valid_dur is not None:
                trace_duration_ms.labels(name=safe_name).observe(valid_dur)
            else:
                log.warning(
                    "telemetry_router: invalid trace duration_ms %r for span %r (dropped observation)",
                    duration_ms,
                    safe_name,
                )
        except Exception:
            pass

    def update_memory_gauges(self) -> None:
        """Refresh all gauge metrics from live singletons."""
        try:
            from backend.memory.episodic import get_episodic_store
            from backend.memory.semantic import get_semantic_store
            from backend.memory.procedural import get_procedural_store
            from .metrics import (
                episodic_count,
                semantic_count,
                semantic_generation,
                procedural_count,
                normalize_label,
                validate_measurement,
            )
            ep_val = validate_measurement(get_episodic_store().count(), non_negative=True)
            if ep_val is not None:
                episodic_count.set(ep_val)
            sem = get_semantic_store()
            gen_val = validate_measurement(sem.generation(), non_negative=True)
            if gen_val is not None:
                semantic_generation.set(gen_val)
            for domain in ["hook", "angle", "signal", "product"]:
                safe_domain = normalize_label("domain", domain)
                dom_count = validate_measurement(sem.count(domain), non_negative=True)
                if dom_count is not None:
                    semantic_count.labels(domain=safe_domain).set(dom_count)
            proc_val = validate_measurement(get_procedural_store().count(), non_negative=True)
            if proc_val is not None:
                procedural_count.set(proc_val)
        except Exception:
            pass

    def update_lineage_gauges(self) -> None:
        try:
            from backend.lineage import get_tracker
            from .metrics import (
                lineage_nodes_total,
                lineage_worldlines_total,
                validate_measurement,
            )
            t = get_tracker()
            nc = validate_measurement(t.node_count(), non_negative=True)
            if nc is not None:
                lineage_nodes_total.set(nc)
            wc = validate_measurement(t.worldline_count(), non_negative=True)
            if wc is not None:
                lineage_worldlines_total.set(wc)
        except Exception:
            pass

    def snapshot(self) -> dict[str, Any]:
        """Capture CognitionSnapshot and return as dict."""
        from .schemas.cognition_snapshot import CognitionSnapshot
        return CognitionSnapshot.capture().to_dict()

    def entropy_report(self, workspace: str = "default") -> dict[str, Any]:
        """Measure and return entropy report as dict."""
        from .metrics import normalize_label
        from .entropy_metrics import measure_entropy
        safe_ws = normalize_label("workspace", workspace)
        return measure_entropy(workspace=safe_ws).to_dict()


_router: TelemetryRouter | None = None
_lock = threading.Lock()


def get_telemetry_router() -> TelemetryRouter:
    global _router
    if _router is None:
        with _lock:
            if _router is None:
                _router = TelemetryRouter()
    return _router
