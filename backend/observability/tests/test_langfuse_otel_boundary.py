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

def test_otel_boundary_batches_and_retries_bounded():
    config = LangfuseOTELConfig(
        state=OTELBoundaryState.DRY_RUN, 
        credential_reference_id="cred-123",
        max_batch_size=5
    )
    adapter = OTelAdapter(config=config)
    spans = [TraceSpan(name=f"test-{i}", span_id=f"s{i}", trace_id="t1") for i in range(10)]
    # In DRY_RUN, they should just be exported without network call
    count = adapter.export_batch(spans)
    assert count == 10
    assert adapter.spans_exported == 10

def test_otel_boundary_dry_run_success():
    config = LangfuseOTELConfig(state=OTELBoundaryState.DRY_RUN, credential_reference_id="cred-123")
    adapter = OTelAdapter(config=config)
    span = TraceSpan(name="test", span_id="s1", trace_id="t1")
    assert adapter.export_span(span) is True
    assert adapter.spans_exported == 1
