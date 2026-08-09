from backend.contracts.adapters import SidecarContext
from backend.integrations.posthog_backend import PostHogAnalyticsAdapter


def test_health_unconfigured_without_credentials(monkeypatch):
    monkeypatch.delenv("POSTHOG_PROJECT_API_KEY", raising=False)
    health = PostHogAnalyticsAdapter().health()
    assert health.configured is False


def test_capture_event_dry_run_makes_no_call():
    adapter = PostHogAnalyticsAdapter()
    result = adapter.capture_event({"event": "service_run", "distinct_id": "ws-1"}, context=SidecarContext(dry_run=True))
    assert result["dry_run"] is True
    assert result["event"] == "service_run"


def test_capture_event_unconfigured_reports_source():
    adapter = PostHogAnalyticsAdapter()
    result = adapter.capture_event({"event": "service_run"}, context=SidecarContext(dry_run=False))
    assert result.get("source") == "unconfigured"


def test_query_events_unconfigured_returns_unconfigured_marker():
    adapter = PostHogAnalyticsAdapter()
    result = adapter.query_events(event_name="service_run")
    assert result[0].get("source") == "unconfigured"
