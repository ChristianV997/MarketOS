from types import SimpleNamespace

from api.routes import canonical_events
from backend.security.rate_limit import reset_rate_limits_for_tests


def test_event_read_routes_are_rate_limited(monkeypatch):
    monkeypatch.setenv("MARKETOS_EVENT_READ_RATE_LIMIT", "1")
    monkeypatch.setenv("MARKETOS_EVENT_READ_RATE_WINDOW_SECONDS", "600")
    reset_rate_limits_for_tests()
    request = SimpleNamespace(client=SimpleNamespace(host="198.51.100.20"))
    first = canonical_events.events(request=request, limit=100, offset=0)
    assert first["read_only"] is True
    second = canonical_events.events(request=request, limit=100, offset=0)
    assert second.status_code == 429
    reset_rate_limits_for_tests()
