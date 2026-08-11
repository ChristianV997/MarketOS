from __future__ import annotations

import json

from api.routes import canonical_events


def test_event_readiness_exposes_redacted_supplier_status(monkeypatch):
    monkeypatch.setenv("CJ_EMAIL", "fixture@example.invalid")
    monkeypatch.setenv("CJ_API_KEY", "fixture-secret")
    monkeypatch.setenv("MARKETOS_SUPPLIER_AUTH_READONLY", "1")
    report = canonical_events.readiness()
    assert report["supplier_auth_readonly"]["configured"] is True
    encoded = json.dumps(report)
    assert "fixture-secret" not in encoded
    assert "fixture@example.invalid" not in encoded
    assert report["read_only"] is True
    assert report["mutated"] is False
