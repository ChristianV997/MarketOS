"""Tests for backend.observability.metrics."""
from backend.observability.metrics import (
    events_published_total, vector_indexed_total, vector_searched_total,
    episodic_count, semantic_count, sleep_cycles_total, cognitive_entropy,
    inference_requests_total, trace_spans_total,
)
from backend.observability.metrics import _NullMetric


def test_null_metric_no_raise():
    m = _NullMetric()
    m.inc()
    m.dec()
    m.set(1.0)
    m.observe(5.0)
    m.labels(foo="bar").inc()


def test_events_published_has_labels():
    events_published_total.labels(event_type="test").inc()


def test_vector_indexed_has_labels():
    vector_indexed_total.labels(collection="hooks").inc(5)


def test_vector_searched_has_labels():
    vector_searched_total.labels(collection="hooks").inc()


def test_episodic_count_set():
    episodic_count.set(42)


def test_semantic_count_labels():
    semantic_count.labels(domain="hook").set(10)


def test_sleep_cycles_total_inc():
    sleep_cycles_total.inc()


def test_cognitive_entropy_labels():
    cognitive_entropy.labels(workspace="default").set(0.3)


def test_inference_requests_labels():
    inference_requests_total.labels(provider="openai", status="ok").inc()


def test_trace_spans_labels():
    trace_spans_total.labels(name="test.op", status="ok").inc()
