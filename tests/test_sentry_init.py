"""Tests for backend.observability.sentry_init.

Sentry's real init() spins up a background transport thread that will try
(and, with a fake DSN, fail) to reach the network — noisy and slow in a
test suite. Tests here monkeypatch sentry_sdk.init itself to a spy so
init_sentry()'s own gating/idempotency logic is verified without ever
touching the network.
"""
import backend.observability.sentry_init as sentry_init


def test_noop_without_dsn(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.setattr(sentry_init, "_initialized", False)

    result = sentry_init.init_sentry()

    assert result is False
    assert sentry_init.is_active() is False


def test_initializes_when_dsn_set(monkeypatch):
    import sentry_sdk
    calls = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: calls.append(kw))
    monkeypatch.setattr(sentry_sdk, "set_tag", lambda k, v: None)
    monkeypatch.setenv("SENTRY_DSN", "https://public@sentry.example.com/1")
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "staging")
    monkeypatch.setattr(sentry_init, "_initialized", False)

    result = sentry_init.init_sentry(component="test")

    assert result is True
    assert sentry_init.is_active() is True
    assert len(calls) == 1
    assert calls[0]["dsn"] == "https://public@sentry.example.com/1"
    assert calls[0]["environment"] == "staging"


def test_idempotent(monkeypatch):
    import sentry_sdk
    calls = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: calls.append(kw))
    monkeypatch.setattr(sentry_sdk, "set_tag", lambda k, v: None)
    monkeypatch.setenv("SENTRY_DSN", "https://public@sentry.example.com/1")
    monkeypatch.setattr(sentry_init, "_initialized", False)

    first = sentry_init.init_sentry()
    second = sentry_init.init_sentry()

    assert first is True
    assert second is True
    assert len(calls) == 1  # second call is a no-op, doesn't re-init


def test_never_raises_when_init_fails(monkeypatch):
    import sentry_sdk

    def _boom(**kw):
        raise RuntimeError("bad dsn")

    monkeypatch.setattr(sentry_sdk, "init", _boom)
    monkeypatch.setenv("SENTRY_DSN", "not-a-valid-dsn")
    monkeypatch.setattr(sentry_init, "_initialized", False)

    result = sentry_init.init_sentry()

    assert result is False
    assert sentry_init.is_active() is False
