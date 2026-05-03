"""Tests for backend.observability.telemetry_router."""
from backend.observability.telemetry_router import TelemetryRouter, get_telemetry_router


def test_singleton_same_instance():
    a = get_telemetry_router()
    b = get_telemetry_router()
    assert a is b


def test_record_event_published_no_raise():
    r = TelemetryRouter()
    r.record_event_published("test.event")


def test_record_vector_indexed_no_raise():
    r = TelemetryRouter()
    r.record_vector_indexed("hooks", 10)


def test_record_vector_searched_no_raise():
    r = TelemetryRouter()
    r.record_vector_searched("hooks", 12.5)


def test_record_inference_no_raise():
    r = TelemetryRouter()
    r.record_inference("openai", "ok", 250.0)


def test_record_trace_span_no_raise():
    r = TelemetryRouter()
    r.record_trace_span("test.op", "ok", 5.0)


def test_update_memory_gauges_no_raise():
    r = TelemetryRouter()
    r.update_memory_gauges()


def test_update_lineage_gauges_no_raise():
    r = TelemetryRouter()
    r.update_lineage_gauges()


def test_record_sleep_cycle_no_raise():
    r = TelemetryRouter()
    r.record_sleep_cycle(500.0, 0.6, 5)


def test_snapshot_returns_dict():
    r = TelemetryRouter()
    result = r.snapshot()
    assert isinstance(result, dict)


def test_entropy_report_returns_dict():
    r = TelemetryRouter()
    result = r.entropy_report(workspace="test")
    assert isinstance(result, dict)
    assert "overall_entropy" in result
