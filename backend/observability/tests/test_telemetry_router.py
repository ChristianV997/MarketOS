"""Tests for backend.observability.telemetry_router."""
import math
import uuid
import logging

from backend.observability.telemetry_router import TelemetryRouter, get_telemetry_router
from backend.observability.metrics import (
    events_published_total,
    vector_indexed_total,
    vector_searched_total,
    vector_search_latency_ms,
    inference_requests_total,
    inference_latency_ms,
    trace_spans_total,
    trace_duration_ms,
    sleep_cycles_total,
    sleep_cycle_duration_ms,
    sleep_compression_ratio,
    sleep_units_created,
)


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


# ── Canonical production operations ───────────────────────────────────────────


def test_record_event_published_canonical_updates_counter():
    r = TelemetryRouter()
    child = events_published_total.labels(event_type="orchestrator.tick")
    before = child._value.get()
    r.record_event_published("orchestrator.tick")
    assert child._value.get() == before + 1.0


def test_record_vector_indexed_canonical_updates_counter():
    r = TelemetryRouter()
    child = vector_indexed_total.labels(collection="products")
    before = child._value.get()
    r.record_vector_indexed("products", 7)
    assert child._value.get() == before + 7.0


def test_record_vector_searched_canonical_updates_counter_and_histogram():
    r = TelemetryRouter()
    cnt = vector_searched_total.labels(collection="hooks")
    hist = vector_search_latency_ms.labels(collection="hooks")
    before_cnt = cnt._value.get()
    before_sum = hist._sum.get()

    r.record_vector_searched("hooks", 14.2)
    assert cnt._value.get() == before_cnt + 1.0
    assert math.isclose(hist._sum.get(), before_sum + 14.2, rel_tol=1e-5)


def test_record_inference_canonical_updates_counter_and_histogram():
    r = TelemetryRouter()
    cnt = inference_requests_total.labels(provider="openai", status="ok")
    hist = inference_latency_ms.labels(provider="openai")
    before_cnt = cnt._value.get()
    before_sum = hist._sum.get()

    r.record_inference("openai", "ok", 180.0)
    assert cnt._value.get() == before_cnt + 1.0
    assert math.isclose(hist._sum.get(), before_sum + 180.0, rel_tol=1e-5)


def test_record_trace_span_canonical_updates_counter_and_histogram():
    r = TelemetryRouter()
    cnt = trace_spans_total.labels(name="agent.product_research", status="ok")
    hist = trace_duration_ms.labels(name="agent.product_research")
    before_cnt = cnt._value.get()
    before_sum = hist._sum.get()

    r.record_trace_span("agent.product_research", "ok", 320.0)
    assert cnt._value.get() == before_cnt + 1.0
    assert math.isclose(hist._sum.get(), before_sum + 320.0, rel_tol=1e-5)


def test_record_sleep_cycle_canonical_updates_metrics():
    r = TelemetryRouter()
    before_cycles = sleep_cycles_total._value.get()
    before_dur_sum = sleep_cycle_duration_ms._sum.get()
    before_units = sleep_units_created._value.get()

    r.record_sleep_cycle(450.0, 0.75, 12)
    assert sleep_cycles_total._value.get() == before_cycles + 1.0
    assert math.isclose(sleep_cycle_duration_ms._sum.get(), before_dur_sum + 450.0, rel_tol=1e-5)
    assert math.isclose(sleep_compression_ratio._value.get(), 0.75)
    assert sleep_units_created._value.get() == before_units + 12.0


# ── Cardinality bounding & Attack resistance ──────────────────────────────────


def test_record_event_published_high_cardinality_bounded():
    # Simulate high-cardinality attack with 300 unique UUID-based event types.
    # Must all collapse into the single 'other' series without error or memory explosion.
    r = TelemetryRouter()
    other_child = events_published_total.labels(event_type="other")
    before = other_child._value.get()

    for _ in range(300):
        unique_type = f"ev_user_action_{uuid.uuid4().hex}"
        r.record_event_published(unique_type)

    assert other_child._value.get() == before + 300.0


def test_record_inference_high_cardinality_bounded():
    # 200 distinct random providers and statuses
    r = TelemetryRouter()
    other_child = inference_requests_total.labels(provider="other", status="other")
    before = other_child._value.get()

    for _ in range(200):
        random_prov = f"custom_model_{uuid.uuid4().hex[:8]}"
        random_stat = f"status_{uuid.uuid4().hex[:8]}"
        r.record_inference(random_prov, random_stat, 100.0)

    assert other_child._value.get() == before + 200.0


# ── Secret, PII, and Path Redaction ────────────────────────────────────────────


def test_record_event_published_pii_and_secrets_redacted():
    # Attack vectors: personal emails, API keys, file paths, newlines
    r = TelemetryRouter()
    other_child = events_published_total.labels(event_type="other")
    before = other_child._value.get()

    canaries = [
        "user.email.victim@domain.com",
        "api.key.sk-live-1234567890abcdef1234567890",
        r"file.access.C:\Windows\System32\config\SAM",
        "/etc/shadow/read",
        "event\r\ninjection\0detected",
        "x" * 128,  # oversized
    ]

    for canary in canaries:
        r.record_event_published(canary)

    # Every canary collapsed into 'other'
    assert other_child._value.get() == before + len(canaries)


def test_record_inference_secrets_and_paths_redacted():
    r = TelemetryRouter()
    other_cnt = inference_requests_total.labels(provider="other", status="other")
    before_cnt = other_cnt._value.get()

    r.record_inference(
        provider="Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
        status=r"C:\keys\secret.pem",
        latency_ms=50.0,
    )
    assert other_cnt._value.get() == before_cnt + 1.0


# ── Invalid & Non-finite measurement safety ────────────────────────────────────


def test_record_vector_indexed_invalid_count_dropped_with_warning(caplog):
    r = TelemetryRouter()
    child = vector_indexed_total.labels(collection="hooks")
    before = child._value.get()

    with caplog.at_level(logging.WARNING):
        # Negative count
        r.record_vector_indexed("hooks", -10)
        # NaN count
        r.record_vector_indexed("hooks", float("nan"))
        # Inf count
        r.record_vector_indexed("hooks", float("inf"))
        # Non-numeric string count
        r.record_vector_indexed("hooks", "five")

    # None of these should increment the counter
    assert child._value.get() == before
    # Warnings should be logged
    assert "invalid vector_indexed count" in caplog.text


def test_record_vector_searched_invalid_latency_dropped(caplog):
    r = TelemetryRouter()
    cnt = vector_searched_total.labels(collection="products")
    hist = vector_search_latency_ms.labels(collection="products")
    before_cnt = cnt._value.get()
    before_sum = hist._sum.get()

    with caplog.at_level(logging.WARNING):
        # Calling with NaN latency
        r.record_vector_searched("products", float("nan"))
        # Calling with negative latency
        r.record_vector_searched("products", -25.0)

    # Counter increments for operation attempt, but histogram observe is dropped
    assert cnt._value.get() == before_cnt + 2.0
    assert hist._sum.get() == before_sum
    assert "invalid vector_searched latency_ms" in caplog.text


def test_record_inference_invalid_latency_dropped(caplog):
    r = TelemetryRouter()
    cnt = inference_requests_total.labels(provider="anthropic", status="ok")
    hist = inference_latency_ms.labels(provider="anthropic")
    before_cnt = cnt._value.get()
    before_sum = hist._sum.get()

    with caplog.at_level(logging.WARNING):
        r.record_inference("anthropic", "ok", float("nan"))
        r.record_inference("anthropic", "ok", -100.0)

    assert cnt._value.get() == before_cnt + 2.0
    assert hist._sum.get() == before_sum
    assert "invalid inference latency_ms" in caplog.text


def test_record_trace_span_invalid_duration_dropped(caplog):
    r = TelemetryRouter()
    cnt = trace_spans_total.labels(name="agent.campaign_qa", status="ok")
    hist = trace_duration_ms.labels(name="agent.campaign_qa")
    before_cnt = cnt._value.get()
    before_sum = hist._sum.get()

    with caplog.at_level(logging.WARNING):
        r.record_trace_span("agent.campaign_qa", "ok", float("nan"))
        r.record_trace_span("agent.campaign_qa", "ok", -5.0)

    assert cnt._value.get() == before_cnt + 2.0
    assert hist._sum.get() == before_sum
    assert "invalid trace duration_ms" in caplog.text


def test_record_sleep_cycle_invalid_measurements_dropped(caplog):
    r = TelemetryRouter()
    before_cycles = sleep_cycles_total._value.get()
    before_dur_sum = sleep_cycle_duration_ms._sum.get()
    before_units = sleep_units_created._value.get()

    with caplog.at_level(logging.WARNING):
        r.record_sleep_cycle(
            duration_ms=float("nan"),
            compression_ratio=float("nan"),
            units_created=-10,
        )

    # sleep_cycles_total increments (the event happened)
    assert sleep_cycles_total._value.get() == before_cycles + 1.0
    # But invalid measurements are dropped
    assert sleep_cycle_duration_ms._sum.get() == before_dur_sum
    assert sleep_units_created._value.get() == before_units
    assert "invalid sleep_cycle duration_ms" in caplog.text
    assert "invalid sleep_cycle compression_ratio" in caplog.text
    assert "invalid sleep_cycle units_created" in caplog.text


# ── Non-string and None inputs ────────────────────────────────────────────────


def test_router_handles_none_and_non_string_types_cleanly():
    r = TelemetryRouter()
    # None values map safely to unknown
    unknown_ev = events_published_total.labels(event_type="unknown")
    before_ev = unknown_ev._value.get()
    r.record_event_published(None)
    assert unknown_ev._value.get() == before_ev + 1.0

    # Passing custom object or dict does not crash or leak pointer
    r.record_event_published(object())
    assert unknown_ev._value.get() == before_ev + 2.0

    unknown_inf = inference_requests_total.labels(provider="unknown", status="unknown")
    before_inf = unknown_inf._value.get()
    r.record_inference(None, object(), 10.0)
    assert unknown_inf._value.get() == before_inf + 1.0


# ── Entropy report workspace sanitization ─────────────────────────────────────


def test_entropy_report_workspace_sanitized():
    r = TelemetryRouter()
    # Canonical workspace works
    rep1 = r.entropy_report(workspace="prod")
    assert isinstance(rep1, dict)

    # Malicious / path-like workspace is sanitized and does not leak to metric
    rep2 = r.entropy_report(workspace=r"C:\Windows\System32\cmd.exe")
    assert isinstance(rep2, dict)
