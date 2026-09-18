"""Tests for Langfuse OTEL boundary."""

from backend.observability.adapters.opentelemetry_adapter import (
    OTelAdapter, LangfuseOTELConfig, OTELBoundaryState
)
from backend.observability.schemas.trace_span import TraceSpan

def test_otel_boundary_disabled_performs_no_call():
    config = LangfuseOTELConfig(state=OTELBoundaryState.DISABLED)
    adapter = OTelAdapter(config=config)
    span = TraceSpan(name="test", span_id="s1", trace_id="t1")
    assert adapter.export_span(span) is False
    assert adapter.spans_exported == 0

def test_otel_boundary_missing_credential_blocks():
    config = LangfuseOTELConfig(state=OTELBoundaryState.DRY_RUN, credential_reference_id=None)
    adapter = OTelAdapter(config=config)
    span = TraceSpan(name="test", span_id="s1", trace_id="t1")
    assert adapter.export_span(span) is False
    assert adapter.config.state == OTELBoundaryState.CONFIGURED_BUT_BLOCKED

def test_otel_boundary_missing_approval_blocks():
    config = LangfuseOTELConfig(state=OTELBoundaryState.APPROVAL_REQUIRED, credential_reference_id="cred-123")
    adapter = OTelAdapter(config=config)
    span = TraceSpan(name="test", span_id="s1", trace_id="t1")
    assert adapter.export_span(span) is False
    assert adapter.spans_exported == 0

def test_otel_boundary_live_export_does_not_call_network():
    config = LangfuseOTELConfig(
        state=OTELBoundaryState.DRY_RUN,
        credential_reference_id="cred-123",
        export_enabled=True
    )
    adapter = OTelAdapter(config=config)
    span = TraceSpan(name="test", span_id="s1", trace_id="t1")
    assert adapter.export_span(span) is False
    assert adapter.config.state == OTELBoundaryState.LIVE_NOT_IMPLEMENTED

def test_otel_boundary_raw_sensitive_fields_redacted():
    config = LangfuseOTELConfig(state=OTELBoundaryState.DRY_RUN, credential_reference_id="cred-123")
    adapter = OTelAdapter(config=config)
    span = TraceSpan(name="test", span_id="s1", trace_id="t1")
    span.events.append({"name": "log", "ts": 12345, "api_key": "secret", "prompt": "some prompt", "safe_field": "hello"})

    # We can inspect the _redact method directly
    payload = adapter._to_otel_span(span)
    redacted = adapter._redact(payload)

    event_attrs = redacted["events"][0]["attributes"]
    assert event_attrs["api_key"] == "[REDACTED]"
    assert event_attrs["prompt"] == "[REDACTED]"
    assert event_attrs["safe_field"] == "hello"

def test_otel_boundary_secret_shaped_value_redacted_under_innocuous_key():
    """Key-name matching alone is not enough: a real-shaped secret stored
    under an innocuous key (e.g. embedded in an error message) must still
    be redacted."""
    config = LangfuseOTELConfig(state=OTELBoundaryState.DRY_RUN, credential_reference_id="cred-123")
    adapter = OTelAdapter(config=config)
    span = TraceSpan(name="test", span_id="s1", trace_id="t1")
    span.error_message = "upstream call failed: token=ghp_abcdefghijklmnopqrstuvwxyz012345"
    payload = adapter._to_otel_span(span)
    redacted = adapter._redact(payload)
    assert redacted["attributes"]["error"] == "[REDACTED]"
    assert "ghp_" not in str(redacted)

def test_otel_boundary_batch_size_is_bounded():
    """Regression: previously max_batch_size was accepted as configuration
    but never enforced -- export_batch exported every span regardless of
    the cap. A batch larger than the cap must only attempt max_batch_size
    spans, never all of them."""
    config = LangfuseOTELConfig(
        state=OTELBoundaryState.DRY_RUN,
        credential_reference_id="cred-123",
        max_batch_size=5
    )
    adapter = OTelAdapter(config=config)
    spans = [TraceSpan(name=f"test-{i}", span_id=f"s{i}", trace_id="t1") for i in range(10)]
    count = adapter.export_batch(spans)
    assert count == 5
    assert adapter.spans_exported == 5

def test_otel_boundary_batch_within_cap_is_unaffected():
    config = LangfuseOTELConfig(
        state=OTELBoundaryState.DRY_RUN,
        credential_reference_id="cred-123",
        max_batch_size=5
    )
    adapter = OTelAdapter(config=config)
    spans = [TraceSpan(name=f"test-{i}", span_id=f"s{i}", trace_id="t1") for i in range(3)]
    count = adapter.export_batch(spans)
    assert count == 3
    assert adapter.spans_exported == 3

def test_otel_boundary_oversized_event_payload_is_dropped():
    """Regression: no per-span payload byte cap existed. An oversized
    event attribute must cause the span to be dropped (not exported,
    not partially exported), not exported unbounded."""
    config = LangfuseOTELConfig(
        state=OTELBoundaryState.DRY_RUN,
        credential_reference_id="cred-123",
        max_payload_bytes=200,
    )
    adapter = OTelAdapter(config=config)
    span = TraceSpan(name="test", span_id="s1", trace_id="t1")
    span.events.append({"name": "log", "ts": 12345, "blob": "x" * 5000})
    assert adapter.export_span(span) is False
    assert adapter.spans_exported == 0

def test_otel_boundary_disabled_destination_is_explicit_and_harmless():
    config = LangfuseOTELConfig(state=OTELBoundaryState.DISABLED, credential_reference_id="cred-123")
    adapter = OTelAdapter(config=config)
    span = TraceSpan(name="test", span_id="s1", trace_id="t1")
    assert adapter.export_span(span) is False
    assert adapter.spans_exported == 0
    # State is unchanged: a disabled destination never transitions state.
    assert adapter.config.state == OTELBoundaryState.DISABLED

def test_otel_boundary_unavailable_destination_is_explicit_and_harmless():
    config = LangfuseOTELConfig(state=OTELBoundaryState.UNAVAILABLE, credential_reference_id="cred-123")
    adapter = OTelAdapter(config=config)
    span = TraceSpan(name="test", span_id="s1", trace_id="t1")
    assert adapter.export_span(span) is False
    assert adapter.spans_exported == 0

def test_otel_boundary_malformed_event_fails_closed_not_raises():
    """A malformed event (not a dict) must not raise out of export_span --
    it must fail closed, matching every other adapter-family convention in
    this repository."""
    config = LangfuseOTELConfig(state=OTELBoundaryState.DRY_RUN, credential_reference_id="cred-123")
    adapter = OTelAdapter(config=config)
    span = TraceSpan(name="test", span_id="s1", trace_id="t1")
    span.events.append("not-a-dict-event")  # type: ignore[arg-type]
    result = adapter.export_span(span)
    assert result is False
    assert adapter.spans_exported == 0

def test_otel_boundary_dry_run_success():
    config = LangfuseOTELConfig(state=OTELBoundaryState.DRY_RUN, credential_reference_id="cred-123")
    adapter = OTelAdapter(config=config)
    span = TraceSpan(name="test", span_id="s1", trace_id="t1")
    assert adapter.export_span(span) is True
    assert adapter.spans_exported == 1

def test_otel_boundary_sanitized_output_is_deterministic():
    """Same span, same config -> byte-identical sanitized payload."""
    config = LangfuseOTELConfig(state=OTELBoundaryState.DRY_RUN, credential_reference_id="cred-123")
    adapter = OTelAdapter(config=config)
    span = TraceSpan(name="test", span_id="s1", trace_id="t1", start_ts=1000.0, end_ts=1001.0)
    span.events.append({"name": "log", "ts": 1000.5, "safe_field": "hello"})
    first = adapter._redact(adapter._to_otel_span(span))
    second = adapter._redact(adapter._to_otel_span(span))
    assert first == second
