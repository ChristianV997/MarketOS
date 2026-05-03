"""backend.observability.tracing — OTel-semantic trace management.

Provides a lightweight trace context that:
  - follows OpenTelemetry span semantics (trace_id, span_id, parent_span_id)
  - is context-local (threading.local) so concurrent operations don't bleed
  - appends completed spans to the durable event log for replay
  - never raises — telemetry must not break production code

Usage::

    from backend.observability.tracing import tracer

    with tracer.span("sleep.consolidation", workspace="prod") as span:
        span.add_event("batch_extracted", size=250)
        do_work()
    # span auto-finishes; trace emitted to event log
"""
from __future__ import annotations

import contextlib
import threading
import time
import uuid
from typing import Any, Generator

from .schemas.trace_span import TraceSpan, SpanStatus
from .schemas.replay_trace import ReplayTrace

_local = threading.local()
_TRACES: dict[str, ReplayTrace] = {}
_TRACES_LOCK = threading.Lock()
_MAX_TRACES = 500


def _current_trace() -> ReplayTrace | None:
    return getattr(_local, "trace", None)


def _current_span() -> TraceSpan | None:
    stack: list[TraceSpan] = getattr(_local, "span_stack", [])
    return stack[-1] if stack else None


class Tracer:
    """Minimal OTel-compatible tracer for cognitive operations."""

    @contextlib.contextmanager
    def span(
        self,
        name: str,
        workspace: str = "default",
        source: str = "",
        **attributes: Any,
    ) -> Generator[TraceSpan, None, None]:
        """Context manager that creates, yields, and finalizes a TraceSpan."""
        parent = _current_span()
        trace  = _current_trace()

        # Start or join a trace
        if trace is None:
            trace = ReplayTrace(
                trace_id=uuid.uuid4().hex[:32],
                name=name,
                workspace=workspace,
            )
            _local.trace = trace
            created_trace = True
        else:
            created_trace = False

        span = TraceSpan.start(
            name=name,
            trace_id=trace.trace_id,
            parent_span_id=parent.span_id if parent else "",
            workspace=workspace,
            source=source,
            **attributes,
        )
        if not trace.root_span_id:
            trace.root_span_id = span.span_id

        # Push span onto thread-local stack
        stack: list[TraceSpan] = getattr(_local, "span_stack", [])
        stack.append(span)
        _local.span_stack = stack
        trace.add_span(span)

        error = ""
        try:
            yield span
        except Exception as exc:
            error = str(exc)
            span.finish(SpanStatus.ERROR, error=error)
            raise
        else:
            span.finish(SpanStatus.OK)
        finally:
            stack.pop()
            if created_trace:
                trace.finish(ok=not error, error=error)
                _local.trace = None
                _register_trace(trace)
                _emit_trace(trace)

    def start_span(self, name: str, **kwargs: Any) -> TraceSpan:
        """Start a span without context manager (caller must call finish())."""
        parent = _current_span()
        trace  = _current_trace()
        if trace is None:
            trace = ReplayTrace(
                trace_id=uuid.uuid4().hex[:32],
                name=name,
                workspace=kwargs.get("workspace", "default"),
            )
            _local.trace = trace

        span = TraceSpan.start(
            name=name,
            trace_id=trace.trace_id,
            parent_span_id=parent.span_id if parent else "",
            **kwargs,
        )
        trace.add_span(span)
        stack: list[TraceSpan] = getattr(_local, "span_stack", [])
        stack.append(span)
        _local.span_stack = stack
        return span

    def finish_span(self, span: TraceSpan, ok: bool = True, error: str = "") -> None:
        status = SpanStatus.OK if ok else SpanStatus.ERROR
        span.finish(status, error=error)
        stack: list[TraceSpan] = getattr(_local, "span_stack", [])
        if span in stack:
            stack.remove(span)

    def recent_traces(self, n: int = 50) -> list[ReplayTrace]:
        with _TRACES_LOCK:
            all_traces = list(_TRACES.values())
        return sorted(all_traces, key=lambda t: t.started_at, reverse=True)[:n]

    def trace_by_id(self, trace_id: str) -> ReplayTrace | None:
        with _TRACES_LOCK:
            return _TRACES.get(trace_id)


def _register_trace(trace: ReplayTrace) -> None:
    with _TRACES_LOCK:
        _TRACES[trace.trace_id] = trace
        # Evict oldest when over cap
        if len(_TRACES) > _MAX_TRACES:
            oldest = min(_TRACES, key=lambda k: _TRACES[k].started_at)
            del _TRACES[oldest]


def _emit_trace(trace: ReplayTrace) -> None:
    try:
        from backend.events.log import append
        append(
            "observability.trace.completed",
            payload={"trace_id": trace.trace_id, "name": trace.name,
                     "duration_ms": trace.duration_ms, "ok": trace.ok,
                     "span_count": trace.span_count},
            source="tracer",
        )
    except Exception:
        pass


tracer = Tracer()
