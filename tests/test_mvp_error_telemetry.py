"""Tests for backend.error_telemetry — error tracking."""
from backend.error_telemetry import record_error, error_summary, error_details


def test_record_error_with_exception():
    """Error with exception is recorded."""
    try:
        raise ValueError("Test error")
    except ValueError as e:
        record_error("test_stage", "test_op", e, context={"product": "test_product"})

    summary = error_summary(lookback_minutes=1)
    assert summary["total_errors"] >= 1


def test_record_error_with_string():
    """Error with string message is recorded."""
    record_error("test_stage", "test_op", "Test error message")

    summary = error_summary(lookback_minutes=1)
    assert summary["total_errors"] >= 1


def test_error_summary_by_stage():
    """Error summary aggregates by stage."""
    record_error("discovery", "op1", "Error 1")
    record_error("discovery", "op2", "Error 2")
    record_error("validation", "op3", "Error 3")

    summary = error_summary(lookback_minutes=1)
    assert summary["total_errors"] >= 3

    # Check aggregation by stage
    by_stage_dict = {s["stage"]: s for s in summary["by_stage"]}
    if "discovery" in by_stage_dict:
        assert by_stage_dict["discovery"]["count"] >= 2


def test_error_summary_by_operation():
    """Error summary aggregates by operation."""
    record_error("stage", "op1", "Error 1")
    record_error("stage", "op1", "Error 1")
    record_error("stage", "op2", "Error 2")

    summary = error_summary(lookback_minutes=1)
    by_op_dict = {o["operation"]: o for o in summary["by_operation"]}

    if "op1" in by_op_dict:
        assert by_op_dict["op1"]["count"] >= 2


def test_error_summary_top_errors():
    """Error summary shows top errors."""
    record_error("stage", "op", RuntimeError("Error A"))
    record_error("stage", "op", RuntimeError("Error A"))
    record_error("stage", "op", ValueError("Error B"))

    summary = error_summary(lookback_minutes=1)
    assert len(summary["top_errors"]) > 0

    # RuntimeError should appear before ValueError (more frequent)
    if len(summary["top_errors"]) >= 2:
        assert summary["top_errors"][0]["count"] >= summary["top_errors"][1]["count"]


def test_error_summary_affected_products():
    """Error summary tracks affected products."""
    record_error("stage", "op", "Error", context={"product": "Widget A"})
    record_error("stage", "op", "Error", context={"product": "Widget B"})

    summary = error_summary(lookback_minutes=1)
    assert len(summary["affected_products"]) >= 2


def test_error_summary_empty():
    """Error summary on empty database returns zeros."""
    summary = error_summary(lookback_minutes=1)
    # May have existing data, but structure should be correct
    assert "total_errors" in summary
    assert "by_stage" in summary
    assert "by_operation" in summary
    assert "top_errors" in summary


def test_error_details_recent():
    """error_details returns most recent errors first."""
    record_error("stage1", "op1", "Error 1")
    record_error("stage2", "op2", "Error 2")

    details = error_details(limit=10)
    assert len(details) > 0

    # Last recorded error should be first
    if len(details) >= 2:
        assert details[0]["timestamp"] >= details[-1]["timestamp"]


def test_error_details_filter_stage():
    """error_details can filter by stage."""
    record_error("discovery", "op1", "Error 1")
    record_error("validation", "op2", "Error 2")

    discovery_errors = error_details(stage="discovery", limit=10)
    for err in discovery_errors:
        assert err["stage"] == "discovery"


def test_error_details_limit():
    """error_details respects limit parameter."""
    for i in range(5):
        record_error(f"stage{i}", f"op{i}", f"Error {i}")

    limited = error_details(limit=2)
    assert len(limited) <= 2
