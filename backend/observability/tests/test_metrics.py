"""Tests for backend.observability.metrics."""
import math
import uuid

from backend.observability.metrics import (
    _NullMetric,
    cognitive_entropy,
    episodic_count,
    event_log_write_failures_total,
    events_published_total,
    inference_requests_total,
    normalize_label,
    semantic_count,
    sleep_cycles_total,
    trace_duration_ms,
    trace_spans_total,
    validate_int_measurement,
    validate_measurement,
    vector_indexed_total,
    vector_searched_total,
)


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


def test_event_log_write_failures_has_backend_label():
    event_log_write_failures_total.labels(backend="event_store").inc()
    event_log_write_failures_total.labels(backend="replay_store").inc()


def test_trace_spans_labels():
    trace_spans_total.labels(name="test.op", status="ok").inc()


# ── Label normalization & cardinality safety ───────────────────────────────────


def test_normalize_label_canonical_values():
    assert normalize_label("event_type", "orchestrator.tick") == "orchestrator.tick"
    assert normalize_label("event_type", "ORCHESTRATOR.TICK") == "orchestrator.tick"
    assert normalize_label("provider", "OpenAI") == "openai"
    assert normalize_label("provider", "anthropic") == "anthropic"
    assert normalize_label("status", "OK") == "ok"
    assert normalize_label("status", "error") == "error"
    assert normalize_label("dry_run", True) == "true"
    assert normalize_label("dry_run", False) == "false"


def test_normalize_label_missing_and_none():
    assert normalize_label("event_type", None) == "unknown"
    assert normalize_label("event_type", "") == "unknown"
    assert normalize_label("event_type", "   ") == "unknown"
    assert normalize_label("provider", None) == "unknown"


def test_normalize_label_non_string_objects_safe():
    # Arbitrary objects must never leak memory addresses or stringify blindly
    obj = object()
    assert normalize_label("provider", obj) == "unknown"
    assert normalize_label("event_type", {"bad": "dict"}) == "unknown"
    assert normalize_label("status", [1, 2, 3]) == "unknown"
    assert normalize_label("name", ValueError("oops")) == "unknown"


def test_normalize_label_pii_redacted():
    # Emails and personal info must never appear in label values
    emails = [
        "user@example.com",
        "admin+prod@internal.company.org",
        "john.doe@sub.domain.co.uk",
    ]
    for email in emails:
        assert normalize_label("provider", email) == "other"
        assert normalize_label("event_type", email) == "other"


def test_normalize_label_secrets_redacted():
    # API keys and bearer tokens must never appear in label values
    secrets = [
        "sk-live-1234567890abcdef1234567890",
        "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
        "ghp_1234567890abcdefghijklmnopqrstuvwxyz",
    ]
    for secret in secrets:
        assert normalize_label("provider", secret) == "other"
        assert normalize_label("event_type", secret) == "other"


def test_normalize_label_paths_redacted():
    # File paths (Windows, POSIX, traversal) must never appear in labels
    paths = [
        r"C:\Windows\System32\drivers\etc\hosts",
        r"D:\Data\MarketOS\secret.key",
        "/etc/passwd",
        "/tmp/telemetry.sock",
        "../../secrets.env",
        r"\\server\share\file",
    ]
    for path in paths:
        assert normalize_label("name", path) == "other"
        assert normalize_label("event_type", path) == "other"


def test_normalize_label_control_characters_redacted():
    # Newlines, carriage returns, null bytes, tabs must be rejected
    invalids = [
        "status\noverflow",
        "line\r\ninjection",
        "null\0byte",
        "tab\tseparated",
    ]
    for inv in invalids:
        assert normalize_label("status", inv) == "other"
        assert normalize_label("name", inv) == "other"


def test_normalize_label_oversized_string_bounded():
    long_str = "a" * 128
    assert normalize_label("name", long_str) == "other"


def test_normalize_label_unlisted_maps_to_other():
    # Any unexpected unlisted string maps to "other" to bound cardinality
    assert normalize_label("provider", "unrecognized_custom_llm") == "other"
    assert normalize_label("collection", "unindexed_user_data") == "other"
    assert normalize_label("event_type", "user.click.random_uuid") == "other"


# ── Measurement validation ─────────────────────────────────────────────────────


def test_validate_measurement():
    assert validate_measurement(10) == 10.0
    assert validate_measurement(12.5) == 12.5
    assert validate_measurement(0) == 0.0
    assert validate_measurement(0.0) == 0.0
    assert validate_measurement("42.5") == 42.5

    # Negative when non_negative=True
    assert validate_measurement(-1.0, non_negative=True) is None
    # Negative when non_negative=False
    assert validate_measurement(-1.0, non_negative=False) == -1.0

    # Non-finite values
    assert validate_measurement(float("nan")) is None
    assert validate_measurement(float("inf")) is None
    assert validate_measurement(float("-inf")) is None

    # Invalids
    assert validate_measurement(None) is None
    assert validate_measurement(True) is None
    assert validate_measurement(False) is None
    assert validate_measurement("invalid") is None
    assert validate_measurement(object()) is None


def test_validate_int_measurement():
    assert validate_int_measurement(5) == 5
    assert validate_int_measurement(0) == 0
    assert validate_int_measurement("12") == 12
    assert validate_int_measurement(15.0) == 15

    # Non-integer float
    assert validate_int_measurement(15.5) is None
    # Negative
    assert validate_int_measurement(-5, non_negative=True) is None
    assert validate_int_measurement(-5, non_negative=False) == -5

    # Non-finite
    assert validate_int_measurement(float("nan")) is None
    assert validate_int_measurement(float("inf")) is None

    # Invalids
    assert validate_int_measurement(None) is None
    assert validate_int_measurement(True) is None
    assert validate_int_measurement("invalid") is None


# ── Metric wrapper runtime behavior ───────────────────────────────────────────


def test_metric_wrapper_nan_inc_dropped():
    child = events_published_total.labels(event_type="orchestrator.tick")
    before = child._value.get()
    child.inc(float("nan"))
    child.inc(float("inf"))
    child.inc(-100)
    assert child._value.get() == before
    # Valid increment still works
    child.inc(1)
    assert child._value.get() == before + 1.0


def test_metric_wrapper_nan_observe_dropped():
    child = trace_duration_ms.labels(name="test.op")
    before_sum = child._sum.get()
    child.observe(float("nan"))
    child.observe(float("inf"))
    child.observe(-50.0)
    assert child._sum.get() == before_sum
    # Valid observe still works
    child.observe(15.0)
    assert child._sum.get() == before_sum + 15.0


def test_metric_wrapper_nan_set_dropped():
    child = cognitive_entropy.labels(workspace="default")
    child.set(0.42)
    assert math.isclose(child._value.get(), 0.42)
    # NaN set is dropped; previous valid value remains
    child.set(float("nan"))
    child.set(float("inf"))
    assert math.isclose(child._value.get(), 0.42)


def test_metric_wrapper_high_cardinality_bounded():
    # Emit 200 unique UUID-based event types directly to metric labels.
    # All of them must collapse into the single 'other' series without error.
    target_other = events_published_total.labels(event_type="other")
    before_other = target_other._value.get()

    for _ in range(200):
        unique_token = f"custom_event_{uuid.uuid4().hex}"
        child = events_published_total.labels(event_type=unique_token)
        # All children map to the single 'other' series child
        assert child._raw_child is target_other._raw_child
        child.inc(1)

    assert target_other._value.get() == before_other + 200.0


def test_metric_wrapper_positional_labels():
    child = inference_requests_total.labels("openai", "ok")
    assert child._raw_child is inference_requests_total.labels(provider="openai", status="ok")._raw_child


def test_null_metric_robustness():
    nm = _NullMetric()
    assert nm.labels("a", "b", foo="bar") is nm
    nm.inc(1)
    nm.dec(1)
    nm.set(2.0)
    nm.observe(3.0)
    assert nm() is nm
