"""Tests for orchestrator.main's AWS standby takeover gate (_await_takeover)."""
from unittest.mock import MagicMock

import orchestrator.main as om


def test_await_takeover_returns_once_heartbeat_stale(monkeypatch):
    monkeypatch.setattr(om, "_AWS_TAKEOVER_AFTER_S", 100.0)
    monkeypatch.setattr(om, "_STANDBY_POLL_S", 0.0)
    monkeypatch.setattr("backend.aws.heartbeat.heartbeat_age_s", lambda: 150.0)
    monkeypatch.setattr(om, "_shutdown_requested", False)

    om._await_takeover()  # must return promptly, not hang


def test_await_takeover_keeps_waiting_on_unknown_age(monkeypatch):
    monkeypatch.setattr(om, "_AWS_TAKEOVER_AFTER_S", 100.0)
    monkeypatch.setattr(om, "_STANDBY_POLL_S", 0.0)

    ages = iter([None, None, 200.0])
    monkeypatch.setattr("backend.aws.heartbeat.heartbeat_age_s", lambda: next(ages))
    monkeypatch.setattr(om, "_shutdown_requested", False)

    om._await_takeover()  # only returns on the third, non-None stale reading


def test_await_takeover_exits_early_on_shutdown_requested(monkeypatch):
    monkeypatch.setattr(om, "_AWS_TAKEOVER_AFTER_S", 100.0)
    monkeypatch.setattr(om, "_STANDBY_POLL_S", 0.0)
    monkeypatch.setattr("backend.aws.heartbeat.heartbeat_age_s", lambda: 5.0)  # fresh, never stale
    monkeypatch.setattr(om, "_shutdown_requested", True)

    om._await_takeover()  # must not hang forever waiting for a stale heartbeat


def test_run_calls_await_takeover_when_standby_enabled(monkeypatch):
    monkeypatch.setattr(om, "_ORCHESTRATOR_STANDBY", True)
    monkeypatch.setattr(om, "_shutdown_requested", True)  # exit run() right after standby check
    await_mock = MagicMock()
    monkeypatch.setattr(om, "_await_takeover", await_mock)
    monkeypatch.setattr(om, "_init_prometheus", lambda: None)
    monkeypatch.setattr(om, "_restore_checkpoint", lambda: None)

    om.run()

    await_mock.assert_called_once()


def test_run_skips_await_takeover_when_not_standby(monkeypatch):
    monkeypatch.setattr(om, "_ORCHESTRATOR_STANDBY", False)
    monkeypatch.setattr(om, "_shutdown_requested", True)  # exit the tick loop's first iteration
    await_mock = MagicMock()
    monkeypatch.setattr(om, "_await_takeover", await_mock)
    monkeypatch.setattr(om, "_init_prometheus", lambda: None)
    monkeypatch.setattr(om, "_restore_checkpoint", lambda: None)

    om.run()

    await_mock.assert_not_called()
