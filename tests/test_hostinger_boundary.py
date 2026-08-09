from backend.integrations.hostinger import HostingerHostingAdapter


def test_health_unconfigured_without_credentials(monkeypatch):
    monkeypatch.delenv("HOSTINGER_API_TOKEN", raising=False)
    health = HostingerHostingAdapter().health()
    assert health.configured is False
    assert health.reachable is False


def test_get_status_unconfigured_reports_source():
    adapter = HostingerHostingAdapter()
    result = adapter.get_status()
    assert result.get("source") == "unconfigured"


def test_list_sites_unconfigured_returns_marker_list():
    adapter = HostingerHostingAdapter()
    result = adapter.list_sites()
    assert result[0].get("source") == "unconfigured"
