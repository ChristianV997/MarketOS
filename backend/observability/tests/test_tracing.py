"""Tests for backend.observability.tracing."""
import pytest
from backend.observability.tracing import tracer, Tracer
from backend.observability.schemas.trace_span import SpanStatus


def test_span_context_manager_ok():
    with tracer.span("test.op", workspace="w1") as span:
        span.add_event("step1", x=1)
    assert span.status == SpanStatus.OK
    assert span.duration_ms is not None
    assert span.duration_ms >= 0


def test_span_captures_error():
    with pytest.raises(ValueError):
        with tracer.span("test.error") as span:
            raise ValueError("boom")
    assert span.status == SpanStatus.ERROR
    assert "boom" in span.error_message


def test_nested_spans_parent_id():
    with tracer.span("outer") as outer:
        with tracer.span("inner") as inner:
            pass
    assert inner.parent_span_id == outer.span_id


def test_recent_traces_populated():
    before = len(tracer.recent_traces(50))
    with tracer.span("recorded.op"):
        pass
    after = tracer.recent_traces(50)
    assert len(after) >= before


def test_trace_by_id():
    with tracer.span("findable") as span:
        tid = span.trace_id
    result = tracer.trace_by_id(tid)
    assert result is not None
    assert result.trace_id == tid


def test_start_finish_span():
    t = Tracer()
    s = t.start_span("manual")
    assert s.span_id
    t.finish_span(s, ok=True)
    assert s.status == SpanStatus.OK


def test_span_add_event():
    with tracer.span("with.events") as span:
        span.add_event("checkpoint", step=1)
    assert len(span.events) == 1
    assert span.events[0]["name"] == "checkpoint"


def test_span_trace_id_propagated():
    with tracer.span("root") as root:
        with tracer.span("child") as child:
            pass
    assert child.trace_id == root.trace_id


def test_recent_traces_sorted_newest_first():
    for name in ("a", "b", "c"):
        with tracer.span(name):
            pass
    traces = tracer.recent_traces(10)
    timestamps = [t.started_at for t in traces[:3]]
    assert timestamps == sorted(timestamps, reverse=True)
