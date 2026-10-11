"""backend.observability.metrics — Prometheus metrics registry for cognition.

All metrics are lazily initialized so importing this module without
prometheus_client installed is safe (they become no-ops via _NullMetric).

Metric label values are strictly bounded against canonical allowlists to
prevent cardinality explosion and ensure caller-supplied values, PII,
secrets, or file paths never create unbounded time-series.
Measurements (latencies, counts, gauges) are validated to be finite and
within domain bounds to protect Prometheus state from NaN poisoning or crashes.
"""
from __future__ import annotations

import logging
import math
import os
import re
from typing import Any

log = logging.getLogger(__name__)

_NAMESPACE = "marketos"

# ── Canonical label allowlists (finite, documented sets) ─────────────────────
# Maximum cardinality for any label is len(allowlist) + 2 ("other", "unknown").

ALLOWED_EVENT_TYPES: frozenset[str] = frozenset({
    # Canonical dotted events
    "orchestrator.tick",
    "signals.updated",
    "simulation.completed",
    "playbook.updated",
    "campaign.updated",
    "anomaly.detected",
    "worker.health",
    "runtime.snapshot",
    "task_inventory",
    "decision.logged",
    "metrics.ingested",
    "heartbeat",
    "runtime.consistency",
    "campaign.launched",
    "skill.executed",
    "skill.failed",
    # Inference events
    "inference.completed",
    "inference.failed",
    "inference.fallback",
    "inference.embedding.completed",
    # Legacy aliases
    "tick",
    "worker",
    "snapshot",
    # Observability & durable event-log events
    "observability.trace.completed",
    "observability.entropy.measured",
    "observability.lineage.tracked",
    "observability.worldline.step",
    "lineage.checkpoint",
    "lineage.node.tracked",
    "sleep.consolidation.completed",
    "sleep.scheduler.tick",
    "sleep.semantic.checkpoint",
    # Test events
    "test",
    "test.event",
    "test_event",
})

ALLOWED_COLLECTIONS: frozenset[str] = frozenset({
    "hooks",
    "products",
    "campaigns",
    "signals",
    "patterns",
    "angles",
    "creatives",
    "test",
    "test_collection",
})

ALLOWED_DOMAINS: frozenset[str] = frozenset({
    "hook",
    "angle",
    "signal",
    "product",
    "creative",
    "test",
})

ALLOWED_PROVIDERS: frozenset[str] = frozenset({
    "openai",
    "anthropic",
    "ollama",
    "litellm",
    "vllm",
    "airllm",
    "andromeda",
    "mock",
    "test",
})

ALLOWED_STATUSES: frozenset[str] = frozenset({
    "ok",
    "error",
    "timeout",
    "rate_limited",
    "fallback",
    "cached",
    "skipped",
    "completed",
    "failed",
    "success",
    "test",
})

ALLOWED_SPAN_NAMES: frozenset[str] = frozenset({
    "agent.product_research",
    "agent.campaign_qa",
    "agent.supplier_comparison",
    "agent.creative_brief",
    "agent.metrics_reconciliation",
    "sleep.consolidation",
    "lineage.track",
    "batch.op",
    "otel.test",
    "test.op",
    "test.error",
    "outer",
    "inner",
    "root",
    "child",
    "findable",
    "with.events",
    "recorded.op",
    "manual",
    "test",
})

ALLOWED_WORKSPACES: frozenset[str] = frozenset({
    "default",
    "prod",
    "staging",
    "test",
    "dev",
    "commerce",
    "w1",
})

ALLOWED_BACKENDS: frozenset[str] = frozenset({
    "event_store",
    "replay_store",
    "test",
})

ALLOWED_OUTCOMES: frozenset[str] = frozenset({
    "success",
    "corrupt",
    "missing",
    "error",
    "test",
})

ALLOWED_MODELS: frozenset[str] = frozenset({
    "qwen:0.5b",
    "qwen2.5:0.5b",
    "llama3.2:1b",
    "deepseek-r1:1.5b",
    "mistral",
    "nomic-embed-text",
    "test",
})

ALLOWED_PHASES: frozenset[str] = frozenset({
    "research",
    "supplier",
    "creative",
    "campaign",
    "reconciliation",
    "test",
})

ALLOWED_DRY_RUN: frozenset[str] = frozenset({
    "true",
    "false",
    "1",
    "0",
})

ALLOWLISTS: dict[str, frozenset[str]] = {
    "event_type": ALLOWED_EVENT_TYPES,
    "collection": ALLOWED_COLLECTIONS,
    "domain": ALLOWED_DOMAINS,
    "provider": ALLOWED_PROVIDERS,
    "status": ALLOWED_STATUSES,
    "name": ALLOWED_SPAN_NAMES,
    "workspace": ALLOWED_WORKSPACES,
    "backend": ALLOWED_BACKENDS,
    "outcome": ALLOWED_OUTCOMES,
    "model": ALLOWED_MODELS,
    "phase": ALLOWED_PHASES,
    "dry_run": ALLOWED_DRY_RUN,
}

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_SECRET_RE = re.compile(
    r"(?:bearer\s+)?[A-Za-z0-9_\-]{24,}|(?:sk-|ghp_|xox[baprs]-)[A-Za-z0-9_\-]+",
    re.I,
)
_PATH_INDICATOR = re.compile(r"[\\/]")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def normalize_label(label_name: str, value: Any) -> str:
    """Normalize and bound a metric label value.

    Guarantees:
    1. Cardinality is strictly bounded: returns canonical allowlisted string,
       'other' (for unlisted/sensitive/path/invalid strings), or 'unknown' (for
       missing/empty/non-string values).
    2. Sensitive data (PII, tokens, file paths) is never echoed in metric labels.
    3. Control characters and non-string objects never leak pointers or corrupt series.
    """
    if value is None:
        return "unknown"

    if isinstance(value, bool):
        val_str = "true" if value else "false"
    elif isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return "unknown"
        val_str = str(value)
    elif isinstance(value, str):
        val_str = value
    elif isinstance(value, bytes):
        try:
            val_str = value.decode("utf-8", errors="ignore")
        except Exception:
            return "unknown"
    else:
        # Non-string object (e.g. dict, list, custom class instance, exception)
        # Never call str() on arbitrary objects as that leaks memory addresses (<... at 0x...>)
        return "unknown"

    val_clean = val_str.strip()
    if not val_clean:
        return "unknown"

    # Enforce maximum length
    if len(val_clean) > 64:
        return "other"

    # Check for control characters
    if _CONTROL_CHAR_RE.search(val_clean):
        return "other"

    # Check for file paths / traversal
    if _PATH_INDICATOR.search(val_clean):
        return "other"

    # Check for PII or secrets
    if _EMAIL_RE.search(val_clean) or _SECRET_RE.search(val_clean):
        return "other"

    candidate = val_clean.lower()
    allowed = ALLOWLISTS.get(label_name)
    if allowed is not None:
        if candidate in allowed:
            return candidate
        return "other"

    # For any unlisted label name, bound to safe generic tokens or "other"
    if candidate in {"default", "test", "other", "unknown", "none", "true", "false", "ok", "error"}:
        return candidate
    return "other"


def validate_measurement(val: Any, non_negative: bool = True) -> float | None:
    """Validate that val is a finite number, optionally non-negative.

    Returns float if valid, None if invalid.
    """
    if val is None or isinstance(val, bool):
        return None
    if not isinstance(val, (int, float)):
        try:
            val = float(val)
        except (ValueError, TypeError):
            return None
    if not math.isfinite(val):
        return None
    if non_negative and val < 0.0:
        return None
    return float(val)


def validate_int_measurement(val: Any, non_negative: bool = True) -> int | None:
    """Validate that val is a finite integer, optionally non-negative.

    Returns int if valid, None if invalid.
    """
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, float):
        if not math.isfinite(val) or not val.is_integer():
            return None
        val = int(val)
    elif not isinstance(val, int):
        try:
            val = int(val)
        except (ValueError, TypeError):
            return None
    if non_negative and val < 0:
        return None
    return int(val)


class _NullMetric:
    """No-op fallback when prometheus_client is unavailable."""
    def labels(self, *args: Any, **kwargs: Any) -> "_NullMetric": return self
    def inc(self, *args: Any, **kwargs: Any) -> None: pass
    def dec(self, *args: Any, **kwargs: Any) -> None: pass
    def set(self, *args: Any, **kwargs: Any) -> None: pass
    def observe(self, *args: Any, **kwargs: Any) -> None: pass
    def __call__(self, *args: Any, **kwargs: Any) -> "_NullMetric": return self


class _SafeMetricChild:
    """Wraps a Prometheus metric child (CounterChild, GaugeChild, etc.)."""

    def __init__(self, raw_child: Any, metric_name: str = "") -> None:
        self._raw_child = raw_child
        self._metric_name = metric_name

    def inc(self, amount: Any = 1) -> None:
        valid = validate_measurement(amount, non_negative=True)
        if valid is None:
            log.warning("metrics: invalid inc amount %r for %s; dropped", amount, self._metric_name)
            return
        try:
            self._raw_child.inc(valid)
        except Exception as exc:
            log.warning("metrics: failed inc on %s: %s", self._metric_name, exc)

    def dec(self, amount: Any = 1) -> None:
        valid = validate_measurement(amount, non_negative=True)
        if valid is None:
            log.warning("metrics: invalid dec amount %r for %s; dropped", amount, self._metric_name)
            return
        try:
            self._raw_child.dec(valid)
        except Exception as exc:
            log.warning("metrics: failed dec on %s: %s", self._metric_name, exc)

    def set(self, value: Any) -> None:
        valid = validate_measurement(value, non_negative=False)
        if valid is None:
            log.warning("metrics: invalid set value %r for %s; dropped", value, self._metric_name)
            return
        try:
            self._raw_child.set(valid)
        except Exception as exc:
            log.warning("metrics: failed set on %s: %s", self._metric_name, exc)

    def observe(self, amount: Any) -> None:
        valid = validate_measurement(amount, non_negative=True)
        if valid is None:
            log.warning("metrics: invalid observe amount %r for %s; dropped", amount, self._metric_name)
            return
        try:
            self._raw_child.observe(valid)
        except Exception as exc:
            log.warning("metrics: failed observe on %s: %s", self._metric_name, exc)

    def __getattr__(self, item: str) -> Any:
        return getattr(self._raw_child, item)


class _SafeMetricWrapper:
    """Wraps a Prometheus metric (Counter, Gauge, Histogram).

    Intercepts labels() to sanitize and bound label values against allowlists.
    Intercepts direct inc(), dec(), set(), observe() to guard measurements.
    Delegates all collector and introspection methods to the underlying metric.
    """

    def __init__(self, raw: Any, name: str, label_names: list[str] | None = None) -> None:
        self._raw = raw
        self._name = name
        self._label_names = tuple(label_names or [])

    def labels(self, *args: Any, **kwargs: Any) -> Any:
        if isinstance(self._raw, _NullMetric):
            return self._raw.labels(*args, **kwargs)

        clean_kwargs: dict[str, str] = {}
        if args:
            for idx, val in enumerate(args):
                if idx < len(self._label_names):
                    lbl_name = self._label_names[idx]
                    clean_kwargs[lbl_name] = normalize_label(lbl_name, val)
                else:
                    clean_kwargs[f"label_{idx}"] = normalize_label(f"label_{idx}", val)

        for k, v in kwargs.items():
            clean_kwargs[k] = normalize_label(k, v)

        try:
            child = self._raw.labels(**clean_kwargs)
            return _SafeMetricChild(child, metric_name=self._name)
        except Exception as exc:
            log.warning(
                "metrics: failed to create child for %s with labels %r: %s",
                self._name,
                clean_kwargs,
                exc,
            )
            return _NullMetric()

    def inc(self, amount: Any = 1) -> None:
        valid = validate_measurement(amount, non_negative=True)
        if valid is None:
            log.warning("metrics: invalid inc amount %r for %s; dropped", amount, self._name)
            return
        try:
            self._raw.inc(valid)
        except Exception as exc:
            log.warning("metrics: failed inc on %s: %s", self._name, exc)

    def dec(self, amount: Any = 1) -> None:
        valid = validate_measurement(amount, non_negative=True)
        if valid is None:
            log.warning("metrics: invalid dec amount %r for %s; dropped", amount, self._name)
            return
        try:
            self._raw.dec(valid)
        except Exception as exc:
            log.warning("metrics: failed dec on %s: %s", self._name, exc)

    def set(self, value: Any) -> None:
        valid = validate_measurement(value, non_negative=False)
        if valid is None:
            log.warning("metrics: invalid set value %r for %s; dropped", value, self._name)
            return
        try:
            self._raw.set(valid)
        except Exception as exc:
            log.warning("metrics: failed set on %s: %s", self._name, exc)

    def observe(self, amount: Any) -> None:
        valid = validate_measurement(amount, non_negative=True)
        if valid is None:
            log.warning("metrics: invalid observe amount %r for %s; dropped", amount, self._name)
            return
        try:
            self._raw.observe(valid)
        except Exception as exc:
            log.warning("metrics: failed observe on %s: %s", self._name, exc)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._raw(*args, **kwargs)

    def __getattr__(self, item: str) -> Any:
        return getattr(self._raw, item)


def _counter(name: str, doc: str, labels: list[str] | None = None):
    try:
        from prometheus_client import Counter
        raw = Counter(f"{_NAMESPACE}_{name}", doc, labels or [])
        return _SafeMetricWrapper(raw, name=f"{_NAMESPACE}_{name}", label_names=labels or [])
    except Exception:
        return _NullMetric()


def _gauge(name: str, doc: str, labels: list[str] | None = None):
    try:
        from prometheus_client import Gauge
        raw = Gauge(f"{_NAMESPACE}_{name}", doc, labels or [])
        return _SafeMetricWrapper(raw, name=f"{_NAMESPACE}_{name}", label_names=labels or [])
    except Exception:
        return _NullMetric()


def _histogram(name: str, doc: str, labels: list[str] | None = None,
               buckets=None):
    try:
        from prometheus_client import Histogram
        kwargs = {"labelnames": labels or []}
        if buckets:
            kwargs["buckets"] = buckets
        raw = Histogram(f"{_NAMESPACE}_{name}", doc, **kwargs)
        return _SafeMetricWrapper(raw, name=f"{_NAMESPACE}_{name}", label_names=labels or [])
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


__all__ = [
    "ALLOWED_BACKENDS",
    "ALLOWED_COLLECTIONS",
    "ALLOWED_DOMAINS",
    "ALLOWED_DRY_RUN",
    "ALLOWED_EVENT_TYPES",
    "ALLOWED_MODELS",
    "ALLOWED_OUTCOMES",
    "ALLOWED_PHASES",
    "ALLOWED_PROVIDERS",
    "ALLOWED_SPAN_NAMES",
    "ALLOWED_STATUSES",
    "ALLOWED_WORKSPACES",
    "ALLOWLISTS",
    "normalize_label",
    "validate_measurement",
    "validate_int_measurement",
    "_counter",
    "_gauge",
    "_histogram",
    "_NullMetric",
    "events_published_total",
    "events_replayed_total",
    "replay_store_size",
    "vector_indexed_total",
    "vector_searched_total",
    "vector_store_size",
    "vector_search_latency_ms",
    "episodic_count",
    "semantic_count",
    "semantic_generation",
    "procedural_count",
    "procedural_success_rate",
    "lineage_nodes_total",
    "lineage_worldlines_total",
    "lineage_depth_max",
    "sleep_cycles_total",
    "sleep_cycle_duration_ms",
    "sleep_compression_ratio",
    "sleep_units_created",
    "checkpoint_writes_total",
    "checkpoint_failures_total",
    "checkpoint_recoveries_total",
    "checkpoint_last_write_ts",
    "event_log_write_failures_total",
    "cognitive_entropy",
    "vector_fragmentation",
    "semantic_duplication",
    "lineage_growth_rate",
    "inference_requests_total",
    "inference_latency_ms",
    "inference_fallbacks_total",
    "ollama_health_check_failures_total",
    "ollama_model_pull_duration_ms",
    "ollama_model_pulls_total",
    "trace_spans_total",
    "trace_duration_ms",
]
