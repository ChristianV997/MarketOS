"""backend.observability.metrics — Prometheus metrics registry for cognition.

All metrics are lazily initialized so importing this module without
prometheus_client installed is safe (they become no-ops via _NullMetric).
"""
from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)

_NAMESPACE = "marketos"


class _NullMetric:
    """No-op fallback when prometheus_client is unavailable."""
    def labels(self, **_: Any) -> "_NullMetric": return self
    def inc(self, *_: Any) -> None: pass
    def dec(self, *_: Any) -> None: pass
    def set(self, *_: Any) -> None: pass
    def observe(self, *_: Any) -> None: pass
    def __call__(self, *_: Any) -> "_NullMetric": return self


def _counter(name: str, doc: str, labels: list[str] | None = None):
    try:
        from prometheus_client import Counter
        return Counter(f"{_NAMESPACE}_{name}", doc, labels or [])
    except Exception:
        return _NullMetric()


def _gauge(name: str, doc: str, labels: list[str] | None = None):
    try:
        from prometheus_client import Gauge
        return Gauge(f"{_NAMESPACE}_{name}", doc, labels or [])
    except Exception:
        return _NullMetric()


def _histogram(name: str, doc: str, labels: list[str] | None = None,
               buckets=None):
    try:
        from prometheus_client import Histogram, DEFAULT_BUCKETS
        kwargs = {"labelnames": labels or []}
        if buckets:
            kwargs["buckets"] = buckets
        return Histogram(f"{_NAMESPACE}_{name}", doc, **kwargs)
    except Exception:
        return _NullMetric()


# ── event spine ───────────────────────────────────────────────────────────────
events_published_total   = _counter("events_published_total",   "Total events published to broker", ["event_type"])
events_replayed_total    = _counter("events_replayed_total",    "Total events replayed on reconnect")
replay_store_size        = _gauge(  "replay_store_size",        "Current event count in replay store")

# ── vector cognition ──────────────────────────────────────────────────────────
vector_indexed_total     = _counter("vector_indexed_total",     "Total records indexed to vector store",  ["collection"])
vector_searched_total    = _counter("vector_searched_total",    "Total vector search operations",         ["collection"])
vector_store_size        = _gauge(  "vector_store_size",        "Records in vector collection",           ["collection"])
vector_search_latency_ms = _histogram("vector_search_latency_ms", "Vector search latency (ms)",           ["collection"],
                                       buckets=[1, 5, 10, 25, 50, 100, 250, 500])

# ── hierarchical memory ───────────────────────────────────────────────────────
episodic_count           = _gauge("episodic_count",             "Episodes in EpisodicStore")
semantic_count           = _gauge("semantic_count",             "Units in SemanticStore",                 ["domain"])
semantic_generation      = _gauge("semantic_generation",        "Current SemanticStore generation")
procedural_count         = _gauge("procedural_count",           "Procedures in ProceduralStore")
procedural_success_rate  = _gauge("procedural_success_rate",    "Average procedure success rate",         ["domain"])

# ── lineage ───────────────────────────────────────────────────────────────────
lineage_nodes_total      = _gauge("lineage_nodes_total",        "Nodes in LineageGraph")
lineage_worldlines_total = _gauge("lineage_worldlines_total",   "Active worldlines")
lineage_depth_max        = _gauge("lineage_depth_max",          "Maximum lineage chain depth")

# ── sleep / consolidation ─────────────────────────────────────────────────────
sleep_cycles_total       = _counter("sleep_cycles_total",       "Total sleep cycles completed")
sleep_cycle_duration_ms  = _histogram("sleep_cycle_duration_ms","Sleep cycle duration (ms)",
                                       buckets=[100, 500, 1000, 5000, 15000, 60000])
sleep_compression_ratio  = _gauge("sleep_compression_ratio",   "Latest consolidation compression ratio")
sleep_units_created      = _counter("sleep_units_created_total","Semantic units created in sleep cycles")

# ── orchestrator checkpointing ────────────────────────────────────────────────
checkpoint_writes_total     = _counter("checkpoint_writes_total",     "Total orchestrator state checkpoint writes")
checkpoint_failures_total   = _counter("checkpoint_failures_total",   "Failed checkpoint writes")
checkpoint_recoveries_total = _counter("checkpoint_recoveries_total", "Startup recoveries from checkpoint", ["outcome"])
checkpoint_last_write_ts    = _gauge(  "checkpoint_last_write_ts",    "Unix timestamp of last successful checkpoint")

# ── event log write failures ─────────────────────────────────────────────────
# backend.events.log.append() and backend.orchestration.event_store.EventStore
# .append() both swallow write failures (except Exception: pass / debug-log
# only) so a caller recording a fact never crashes — but that meant a silent
# disk-full/corruption event produced zero operator-visible signal. This
# counter closes that gap without changing the fail-silent behavior itself.
event_log_write_failures_total = _counter(
    "event_log_write_failures_total", "Failed event-log append() calls", ["backend"])

# ── entropy ───────────────────────────────────────────────────────────────────
cognitive_entropy        = _gauge("cognitive_entropy",          "Overall cognitive entropy [0,1]",        ["workspace"])
vector_fragmentation     = _gauge("vector_fragmentation",       "Vector store fragmentation [0,1]")
semantic_duplication     = _gauge("semantic_duplication",       "Semantic duplication rate [0,1]")
lineage_growth_rate      = _gauge("lineage_growth_rate",        "Lineage nodes added per hour")

# ── inference ─────────────────────────────────────────────────────────────────
inference_requests_total = _counter("inference_requests_total", "Inference requests",                    ["provider", "status"])
inference_latency_ms     = _histogram("inference_latency_ms",   "Inference latency (ms)",                ["provider"],
                                       buckets=[50, 100, 200, 500, 1000, 3000, 10000])
inference_fallbacks_total= _counter("inference_fallbacks_total","Provider fallbacks triggered")

# ── ollama (local inference) ─────────────────────────────────────────────────
ollama_health_check_failures_total = _counter(
    "ollama_health_check_failures_total", "Ollama daemon health-check failures")
ollama_model_pull_duration_ms = _histogram(
    "ollama_model_pull_duration_ms", "Ollama model pull duration (ms)", ["model"],
    buckets=[100, 500, 1000, 5000, 15000, 60000, 300000])
ollama_model_pulls_total = _counter(
    "ollama_model_pulls_total", "Ollama model pull attempts", ["model", "status"])

# ── tracing ───────────────────────────────────────────────────────────────────
trace_spans_total        = _counter("trace_spans_total",        "Trace spans completed",                  ["name", "status"])
trace_duration_ms        = _histogram("trace_duration_ms",      "Trace span duration (ms)",               ["name"],
                                       buckets=[1, 5, 10, 50, 100, 500, 2000])
