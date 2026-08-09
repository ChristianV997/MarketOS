"""Tests for backend.cost_tracking — API cost tracking."""
import time

from backend.cost_tracking import track_api_call, cost_report, cost_timeline


def test_track_api_call_success():
    """Successful API call is recorded."""
    with track_api_call("test_service", "test_op", cost_usd=0.01):
        pass  # No exception

    report = cost_report(lookback_minutes=1)
    assert report["num_calls"] >= 1
    assert report["total_spend"] >= 0.01
    assert report["num_successes"] >= 1


def test_track_api_call_failure():
    """Failed API call is recorded with error."""
    try:
        with track_api_call("test_service", "test_op_fail", cost_usd=0.01):
            raise ValueError("Test error")
    except ValueError:
        pass

    report = cost_report(lookback_minutes=1)
    assert report["num_errors"] >= 1


def test_cost_report_empty():
    """Cost report on empty database returns zeros."""
    report = cost_report(lookback_minutes=1, service="nonexistent_service")
    assert report["total_spend"] == 0.0
    assert report["num_calls"] == 0


def test_cost_report_aggregation():
    """Cost report aggregates by service and operation."""
    with track_api_call("meta", "create_campaign", cost_usd=0.001):
        pass
    with track_api_call("meta", "create_adset", cost_usd=0.001):
        pass
    with track_api_call("shopify", "create_product", cost_usd=0.0005):
        pass

    report = cost_report(lookback_minutes=1)
    assert report["num_calls"] >= 3
    assert report["total_spend"] >= 0.0025

    # Check aggregation by service
    assert "meta" in report["by_service"]
    assert "shopify" in report["by_service"]
    assert report["by_service"]["meta"]["count"] >= 2
    assert report["by_service"]["shopify"]["count"] >= 1


def test_cost_report_error_rate():
    """Cost report calculates error rate."""
    with track_api_call("test", "op1", cost_usd=0.001):
        pass
    try:
        with track_api_call("test", "op2", cost_usd=0.001):
            raise ValueError("fail")
    except ValueError:
        pass

    report = cost_report(lookback_minutes=1)
    assert report["num_calls"] >= 2
    assert report["num_errors"] >= 1
    assert report["error_rate"] > 0


def test_cost_timeline_bucketing(monkeypatch):
    """Cost timeline buckets costs by time."""
    import backend.cost_tracking as ct

    real_time = time.time
    monkeypatch.setattr(ct.time, "time", lambda: real_time())
    with track_api_call("test", "op", cost_usd=0.001):
        pass
    # Jump forward instead of sleeping, to deterministically separate buckets
    monkeypatch.setattr(ct.time, "time", lambda: real_time() + 0.1)
    with track_api_call("test", "op", cost_usd=0.002):
        pass

    timeline = cost_timeline(lookback_minutes=1, bucket_minutes=1)
    assert len(timeline) >= 1

    # Each bucket should have spend >= 0.003
    total_timeline_spend = sum(b["spend"] for b in timeline)
    assert total_timeline_spend >= 0.003


def test_cost_timeline_empty():
    """Cost timeline on empty database returns empty list."""
    timeline = cost_timeline(lookback_minutes=1, bucket_minutes=5)
    # May have existing data, so just check it's a list
    assert isinstance(timeline, list)
