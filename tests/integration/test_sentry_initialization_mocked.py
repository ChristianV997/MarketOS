import pytest

sentry_sdk = pytest.importorskip("sentry_sdk")

import backend.observability.phase1_telemetry as telemetry
import backend.observability.sentry_init as sentry_init


def test_missing_dsn_does_not_initialize(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.setattr(sentry_init, "_initialized", False)
    assert telemetry.initialize_phase1_telemetry("test") is False


def test_sentry_initialization_is_sanitized_and_pii_disabled(monkeypatch):
    calls = []
    monkeypatch.setenv("SENTRY_DSN", "https://public@sentry.example.com/1")
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "staging")
    monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "0.05")
    monkeypatch.setattr(sentry_init, "_initialized", False)
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(sentry_sdk, "set_tag", lambda *_args: None)
    assert telemetry.initialize_phase1_telemetry("test") is True
    assert calls[0]["send_default_pii"] is False
    assert calls[0]["traces_sample_rate"] == 0.05
    assert callable(calls[0]["before_send"])
    sanitized = calls[0]["before_send"]({"user": {"email": "person@example.test"}}, {})
    assert "user" not in sanitized
