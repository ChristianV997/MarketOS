"""Tests for backend.observability.adapters."""
from backend.observability.adapters.opentelemetry_adapter import OTelAdapter, get_otel_adapter
from backend.observability.adapters.lineage_adapter import emit_lineage_tracked, lineage_summary
from backend.observability.adapters.vector_adapter import emit_indexed, emit_searched, vector_summary
from backend.observability.adapters.replay_adapter import (
    emit_event_published, emit_replay_store_size, replay_summary,
)
from backend.observability.adapters.scheduler_adapter import emit_sleep_cycle, scheduler_status
from backend.observability.adapters.memory_adapter import emit_memory_gauges, memory_summary


def test_otel_adapter_singleton():
    a = get_otel_adapter()
    b = get_otel_adapter()
    assert a is b


def test_otel_export_no_endpoint():
    adapter = OTelAdapter(endpoint="", service_name="test")
    from backend.observability.tracing import tracer
    with tracer.span("otel.test") as span:
        pass
    result = adapter.export_span(span)
    assert result is True


def test_otel_export_batch():
    from backend.observability.tracing import tracer
    spans = []
    for _ in range(3):
        with tracer.span("batch.op") as sp:
            pass
        spans.append(sp)
    adapter = OTelAdapter()
    count = adapter.export_batch(spans)
    assert count == 3


def test_emit_lineage_tracked_no_raise():
    emit_lineage_tracked("n1", "ws", "src", ["p1"], "test.event")


def test_lineage_summary_returns_dict():
    r = lineage_summary("default")
    assert isinstance(r, dict)
    assert "node_count" in r


def test_emit_indexed_no_raise():
    emit_indexed("hooks", 5)


def test_emit_searched_no_raise():
    emit_searched("hooks", 10.0)


def test_vector_summary_returns_dict():
    r = vector_summary()
    assert isinstance(r, dict)
    assert "collections" in r


def test_emit_event_published_no_raise():
    emit_event_published("test.event")


def test_emit_replay_store_size_no_raise():
    emit_replay_store_size()


def test_replay_summary_returns_dict():
    r = replay_summary()
    assert isinstance(r, dict)
    assert "count" in r


def test_emit_sleep_cycle_no_raise():
    emit_sleep_cycle(100.0, 0.5, 3)


def test_scheduler_status_returns_dict():
    r = scheduler_status()
    assert isinstance(r, dict)
    assert "running" in r


def test_emit_memory_gauges_no_raise():
    emit_memory_gauges()


def test_memory_summary_returns_dict():
    r = memory_summary("default")
    assert isinstance(r, dict)
    assert "episodic_count" in r
