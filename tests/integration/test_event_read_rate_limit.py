from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.routes import canonical_events
from backend.security.rate_limit import reset_rate_limits_for_tests


def test_event_read_routes_are_rate_limited(monkeypatch):
    monkeypatch.setenv("MARKETOS_EVENT_READ_RATE_LIMIT", "1")
    monkeypatch.setenv("MARKETOS_EVENT_READ_RATE_WINDOW_SECONDS", "600")
    reset_rate_limits_for_tests()
    request = SimpleNamespace(client=SimpleNamespace(host="198.51.100.20"))
    canonical_events._admit_read(request)
    with pytest.raises(HTTPException) as refused:
        canonical_events._admit_read(request)
    assert refused.value.status_code == 429
    assert refused.value.headers["Retry-After"]
    assert refused.value.detail["status"] == "rate_limited"
    reset_rate_limits_for_tests()
